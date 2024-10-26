import argparse
import os
import pdb
import re
import pathlib
import logging
import json
import datetime


from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import jsonschema

# SCOPES is tied to the user_token. If this changes,
# regenerate the user_token.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

CONFIG_SCHEMA_V1 = """
{
	"$schema": "http://json-schema.org/draft-07/schema#",
	"type": "object",
	"properties": {
		"Version": {
			"type": "string",
			"enum": ["1.0.0"]
		},
		"idle_time_to_archive_days" : {
			"type": "integer", 
			"minium": 0, 
			"maximum": 1095
		},
		"Labels": {
			"type": "object",
			"properties": {
				"RespondTo": {"type": "string"},
				"Archive": {"type": "string"}
			},
			"required": ["RespondTo", "Archive"]
		},
		"Secrets" : { 
			"type": "object",
			"properties": {
				"project_token_path": {
					"type": "string"
				},
				"user_token_path": {
					"type": "string"
				}
			}
		}
	},
	"required": ["Version", "Labels", "Secrets", "idle_time_to_archive_days"]
}
"""


class RFC3339Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.datetime.fromtimestamp(
            record.created, datetime.timezone.utc
        ).isoformat()

    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Add any extra attributes to the log
        if hasattr(record, "extras"):
            log_data["extras"] = record.extras

        return json.dumps(log_data)


def authenticate_gmail(config):
    creds = None
    if os.path.exists(config.secrets.user_token_path):
        creds = Credentials.from_authorized_user_file(
            config.secrets.user_token_path,
            SCOPES,
        )
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.secrets.project_token_path,
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(config.secrets.user_token_path, "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def get_label_id(service, label_name):
    # Fetch Gmail label ID by label name
    # TODO: This would be more efficent as a list of labels to resolve instead of each function call resolving one label...
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    for label in labels:
        if label["name"] == label_name:
            return label["id"]
    raise ValueError(f"Label '{label_name}' not found")


def remove_label_add_label_msgs(
    service, config, thread_messages, remove_label, add_label
):
    # Add the label to the first message, strip labels from all inner messages
    if config.dry_run:
        config.logger.warning("Skipping label changes due to dry-run")
        return
    service.users().messages().modify(
        userId="me",
        id=thread_messages[0]["id"],
        body={"removeLabelIds": [remove_label], "addLabelIds": [add_label]},
    ).execute()
    for message in thread_messages[1:]:
        service.users().messages().modify(
            userId="me",
            id=message["id"],
            body={"removeLabelIds": [remove_label, add_label]},
        ).execute()


def get_email_subject(message):
    headers = message["payload"].get("headers", [])
    for header in headers:
        if header["name"] == "Subject":
            return header["value"]
    return "(No Subject)"


def check_threads(
    service, config, search_label, remove_label, add_label, condition_func
):
    page_token = None

    threads_reviewed = 0

    while True:
        results = (
            service.users()
            .threads()
            .list(userId="me", labelIds=[search_label], pageToken=page_token)
            .execute()
        )

        thread_summaries = results.get("threads", [])

        if not thread_summaries:
            config.logging.warning(
                "No messages found with search label",
                extra={
                    "extras": {
                        "search_label_id": search_label,
                    }
                },
            )
            return

        for thread_summary in thread_summaries:
            thread_id = thread_summary["id"]
            thread_messages = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="metadata")
                .execute()["messages"]
            )
            threads_reviewed += 1
            if condition_func(thread_messages):
                email_subject = get_email_subject(thread_messages[0])
                config.logger.info(
                    "Thread found meeting conditions",
                    extra={"extras": {"subject": email_subject}},
                )
                remove_label_add_label_msgs(
                    service, config, thread_messages, remove_label, add_label
                )

        # Check if there is another page to review
        page_token = results.get("nextPageToken")
        if not page_token:
            # no more pages to review
            config.logger.info(
                "Done reviewing threads with search_label",
                extra={
                    "extras": {
                        "search_label_id": search_label,
                        "thread_cnt": threads_reviewed,
                    }
                },
            )
            break
        config.logger.info("Retrieving next page of results")


def condition_reply_to_archive(messages, clean_out_date):
    # Check if all messages are read and older than 1 week
    for msg in messages:
        headers = msg["payload"].get("headers", [])
        is_unread = "UNREAD" in msg["labelIds"]
        date_str = next((h["value"] for h in headers if h["name"] == "Date"), None)
        cleaned_date_str = re.sub(r"\s+\([A-Za-z]+\)", "", date_str)
        msg_date = datetime.datetime.strptime(
            cleaned_date_str, "%a, %d %b %Y %H:%M:%S %z"
        )
        if is_unread or msg_date > clean_out_date:
            return False
    return True

def condition_archive_to_reply(messages):
    # Check if any message is unread
    for msg in messages:
        if "UNREAD" in msg["labelIds"]:
            return True
    return False


class Labels:
    respond_to_label: str
    archive_label: str

    def __init__(
        self,
        respond_to: str,
        archive: str,
    ):
        self.respond_to_label = respond_to
        self.archive_label = archive


class Secrets:
    project_token_path: pathlib.Path
    user_token_path: pathlib.Path

    def __init__(
        self,
        project_path_str: str,
        user_token_path_str: str,
    ):
        self.project_token_path = pathlib.Path(project_path_str)
        self.user_token_path = pathlib.Path(user_token_path_str)


class Config_V1:
    idle_time_to_archive_in_days: int
    labels: Labels
    secrets: Secrets
    dry_run: bool
    logger: any

    def __init__(
        self,
        idle_time_to_archive_in_days: int,
        dry_run: bool,
        logger,
        labels: Labels,
        secrets: Secrets,
    ):
        self.idle_time_to_archive_in_days = idle_time_to_archive_in_days
        self.dry_run = dry_run
        self.logger = logger
        self.labels = labels
        self.secrets = secrets


def load_config(args, logger):
    config_path = args.config
    dry_run = not args.prod_run

    schema = json.loads(CONFIG_SCHEMA_V1)
    config_json = None
    with open(config_path, "r") as file_handle:
        config_json = json.load(file_handle)
    # Let the error bubble up, the traceback is the user feedback
    jsonschema.validate(instance=config_json, schema=schema)

    config = Config_V1(
        config_json["idle_time_to_archive_days"],
        dry_run,
        logger,
        Labels(
            config_json["Labels"]["RespondTo"],
            config_json["Labels"]["Archive"],
        ),
        Secrets(
            config_json["Secrets"]["project_token_path"],
            config_json["Secrets"]["user_token_path"],
        ),
    )
    return config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update gmail labels to focus on unread, important, emails"
    )
    parser.add_argument(
        "--config",
        default="./config.json",
        help="Path to the configuration file (default: ./config.json)",
    )
    parser.add_argument(
        "--prod-run",
        action=argparse.BooleanOptionalAction,
    )
    return parser.parse_args()


def main():

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setFormatter(RFC3339Formatter())
    logger.addHandler(handler)

    args = parse_args()
    config = load_config(args, logger)

    # Authenticate and build the Gmail API service
    service = authenticate_gmail(config)

    # Resolve label IDs
    logger.info(
        "Resolving label ids",
        extra={
            "extras": {
                "reply": config.labels.respond_to_label,
                "archive": config.labels.archive_label,
            },
        },
    )
    reply_label = get_label_id(service, config.labels.respond_to_label)
    config.logger.debug(
        "Respond To Label mapped",
        extra={
            "extras": {
                "label": config.labels.respond_to_label,
                "id": reply_label,
            },
        },
    )
    archive_label = get_label_id(service, config.labels.archive_label)
    config.logger.debug(
        "Archive Label mapped",
        extra={
            "extras": {
                "label": config.labels.archive_label,
                "id": archive_label,
            },
        },
    )
    logger.info("Starting check for reply to archive")
    clean_out_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        days=config.idle_time_to_archive_in_days
    )
    config.logger.info(
        "Clean out date calculated", extra={"extras": {"date": str(clean_out_date)}}
    )

    check_threads(
        service,
        config,
        reply_label,
        reply_label,
        archive_label,
        lambda messages: condition_reply_to_archive(messages, clean_out_date),
    )

    logger.info("Starting check for archive to reply")
    check_threads(
        service,
        config,
        archive_label,
        archive_label,
        reply_label,
        condition_archive_to_reply,
    )


if __name__ == "__main__":
    main()

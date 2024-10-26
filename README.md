# Gmail Labeler

Gmail Labeler is a script for managing labels in gmail. It assumes that there are two labels of interest, where the names of the labels are varible:
- Respond To: This label covers emails that should be responded to and represent open items.
- Archive: This label covers emails that had the respond to label, but are now closed. If someone replies to an email with this label, the script will change the label to "Respond To".

## Why use Gmail Labeler?

My workflow for email consists of labeling anything that is worth responding to throughout the day, then taking the time to reply when I can. As time went on my "Respond To" got very large. Gmail makes it really hard to find unread email chains with a label on them, so I started relabeling older messages with "Archive". But if someone replied to a message in "Archive" I'd miss it unless I went through all of those from time to time. This was all annoying and manual so I wrote a script to handle all of this for me.

# Configuration

Configuration is done via a JSON file which specifies a few properties. In the interests of laziness the full schema is in `gmail_labeler.py` under `CONFIG_SCHMA_V1`. A sample config looks like:

```json
{  
       "Version": "1.0.0",  
       "idle_time_to_archive_days": 7,  
       "Labels": {  
               "RespondTo": "Respond To",  
               "Archive": "Responded Archive"  
       },  
       "Secrets": {  
               "project_token_path": "../gmail-labeler-secrets/gmail_labeler_client_secret.json",  
               "user_token_path": "../gmail-labeler-secrets/gmail_labeler_client_token.json"  
       }  
}
```

Because this uses Google APIs a Google Project with the Gmail API turned on is required and the account this is used for will need to undergo an oauth authZ flow to generate the user token required to access the accounts emails.

import sys
import ssl
import certifi
import yaml
import os
from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient

# get config yaml file
config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

ssl_context = ssl.create_default_context(cafile=certifi.where())

if os.path.exists(config_path):
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    # Get user token from config once for reuse
    token = config["user_token"]
    
    # Create Slack client once for reuse
    client = WebClient(token=token, ssl=ssl_context)
    

mcp = FastMCP("slack")

@mcp.tool()
def slack_setup(user_token: str) -> str:
    """
    Setup the Slack config file.

    Args:
        user_token: The user token to use for the Slack client

    Returns:
        str: A confirmation message if successful, or an error message if the setup failed
    """
    try:
        # Create initial config structure
        initial_config = {
            "user_token": user_token,
            "users": {},
            "channels": {}
        }
        
        # Write initial config to file
        with open(config_path, 'w') as file:
            yaml.safe_dump(initial_config, file, default_flow_style=False, sort_keys=False)
        
        # Update the global client with new token
        global client
        client = WebClient(token=user_token, ssl=ssl_context)
        
        # Populate users and channels
        user_result = _get_user_ids()
        channel_result = _get_channel_ids()
        
        return f"Slack setup completed successfully! {user_result}. {channel_result}."
        
    except Exception as e:
        return f"Error during setup: {str(e)}"

@mcp.tool()
def send_message_to_user(user_name: str, message: str) -> str:
    """
    Send a direct message to a user in Slack.
    
    Args:
        user_name: The name of the user to send the message to (e.g., "andy")
        message: The text content of the message to send
        
    Returns:
        str: A confirmation message if successful, or an error message if the send failed
    """
    try:        
        # Reload config to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        # Get user ID from the config
        user_name = user_name.lower()
        if user_name not in current_config["users"]:
            return f"Error: User '{user_name}' not found in config"
        
        user_id = current_config["users"][user_name]
        
        # Send direct message to user (use user_id as channel)
        response = client.chat_postMessage(
            channel=user_id,
            text=message
        )
        
        if response["ok"]:
            return f"Direct message sent successfully to {user_name}!"
        else:
            return f"Error: {response['error']}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def send_message_to_channel(channel_name: str, message: str) -> str:
    """
    Send a message to a channel in Slack.
    
    Args:
        channel_name: The name of the channel to send the message to (e.g., "mcp-server")
        message: The text content of the message to send
        
    Returns:
        str: A confirmation message if successful, or an error message if the send failed
    """
    try:        
        # Reload config to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        # Get channel ID from the config
        channel_name = channel_name.lower()
        if channel_name not in current_config["channels"]:
            return f"Error: Channel '{channel_name}' not found in config"
        
        channel_id = current_config["channels"][channel_name]
        
        # Send message to channel
        response = client.chat_postMessage(
            channel=channel_id,
            text=message
        )
        
        if response["ok"]:
            return f"Message sent successfully to #{channel_name}!"
        else:
            return f"Error: {response['error']}"
    except Exception as e:
        return f"Error: {str(e)}"

def _get_channel_ids():
    try:
        # Reload config from file to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)

        response = client.conversations_list()

        if response["ok"]:
            # Ensure channels section exists in config
            if "channels" not in current_config:
                current_config["channels"] = {}
            
            new_channels_added = 0

            for channel in response["channels"]:
                # Skip archived channels and only include public/private channels
                if not channel.get("is_archived", False) and channel.get("is_member", True):
                    name = channel.get("name", "")
                    channel_id = channel.get("id", "")
                    
                    # Check if channel already exists in config
                    if name.lower() not in current_config["channels"]:
                        # Add new channel to config
                        current_config["channels"][name.lower()] = channel_id
                        new_channels_added += 1

            # Write updated config back to file
            if new_channels_added > 0:
                with open(config_path, 'w') as file:
                    yaml.safe_dump(current_config, file, default_flow_style=False, sort_keys=False) 
            return f"Config updated! Added {new_channels_added}" 
        else:
            return f"Error: {response['error']}"
            
    except Exception as e:
        return f"Error: {str(e)}"

def _get_user_ids():
    try:
        # Reload config from file to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        # Get all users in the workspace
        response = client.users_list()
        
        if response["ok"]:
            # Ensure users section exists in config
            if "users" not in current_config:
                current_config["users"] = {}
            
            new_users_added = 0
            
            for user in response["members"]:
                # Skip bots and deleted users
                if not user.get("is_bot", False) and not user.get("deleted", False):
                    name = user.get("name", "")
                    user_id = user.get("id", "")
                    
                    # Check if user already exists in config
                    if name.lower() not in current_config["users"]:
                        # Add new user to config
                        current_config["users"][name.lower()] = user_id
                        new_users_added += 1
            
            # Write updated config back to file
            if new_users_added > 0:
                with open(config_path, 'w') as file:
                    yaml.safe_dump(current_config, file, default_flow_style=False, sort_keys=False)
            
            return f"Config updated! Added {new_users_added}"
        else:
            return f"Error: {response['error']}"
            
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()
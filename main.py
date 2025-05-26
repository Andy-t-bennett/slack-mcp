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

# Initialize client as None - will be set up when config is loaded
client = None

try:
    if os.path.exists(config_path):
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
        
        # Get user token from config once for reuse
        token = config["user_token"]
        
        # Create Slack client once for reuse
        client = WebClient(token=token, ssl=ssl_context)
except Exception as e:
    # Server can still start without config - setup will handle this
    print(f"Warning: Could not load config on startup: {e}", file=sys.stderr)

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
        user_name: The name of the user to send the message to (e.g., "andy", "Andy Bennett", "abennett1297")
        message: The text content of the message to send
        
    Returns:
        str: A confirmation message if successful, or an error message if the send failed
    """
    try:
        # Check if client is initialized
        if client is None:
            return "Slack not configured. Please ask me to setup slack and provide your user token."
        
        # Use the new user lookup function
        user_id = _get_slack_user(user_name)
        if user_id is None:
            return f"Error: User '{user_name}' not found in config"
        
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
def send_message_to_channel(channel_name: str, message: str, users: list[str] = None) -> str:
    """
    Send a message to a channel in Slack, optionally mentioning specific users.
    
    Args:
        channel_name: The name of the channel to send the message to (e.g., "mcp-server")
        message: The text content of the message to send
        users: Optional list of user names to mention (e.g., ["andy", "alec"])
        
    Returns:
        str: A confirmation message if successful, or an error message if the send failed
    """
    try:
        # Check if client is initialized
        if client is None:
            return "Slack not configured. Please ask me to setup slack and provide your user token."
        
        # Reload config to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        # Get channel ID from the config
        channel_name = channel_name.lower()
        if channel_name not in current_config["channels"]:
            return f"Error: Channel '{channel_name}' not found in config"
        
        channel_id = current_config["channels"][channel_name]

        # Build mentions if users are specified
        mentions = []
        if users:
            for user in users:
                user_id = _get_slack_user(user)
                if user_id:
                    mentions.append(f"<@{user_id}>")
                else:
                    return f"Error: User '{user}' not found in config"
        
        # Construct final message with mentions at the beginning
        if mentions:
            final_message = f"{' '.join(mentions)} {message}"
        else:
            final_message = message
        
        # Send message to channel
        response = client.chat_postMessage(
            channel=channel_id,
            text=final_message
        )
        
        if response["ok"]:
            mentioned_users_str = f" (mentioning {', '.join(users)})" if users else ""
            return f"Message sent successfully to #{channel_name}!{mentioned_users_str}"
        else:
            return f"Error: {response['error']}"
    except Exception as e:
        return f"Error: {str(e)}"

def _get_slack_user(name: str) -> str:
    """
    Find a Slack user by various identifiers (username, display name, real name, etc.)
    
    Args:
        name: The name to search for (can be username, display name, real name, etc.)
        
    Returns:
        str: The user ID if found, None if not found
    """
    try:
        # Reload config to get latest data
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        if "users" not in current_config:
            return None
            
        name_lower = name.lower()
        
        # Search through all users for a match
        for user_data in current_config["users"].values():
            # Check all possible name fields
            if (user_data.get("username", "").lower() == name_lower or
                user_data.get("display_name", "").lower() == name_lower or
                user_data.get("real_name", "").lower() == name_lower or
                user_data.get("first_name", "").lower() == name_lower):
                return user_data["id"]
        
        return None
    
    except Exception as e:
        return None

def _get_channel_ids():
    try:
        # Check if client is initialized
        if client is None:
            return "Error: Slack client not initialized"
        
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
        # Check if client is initialized
        if client is None:
            return "Error: Slack client not initialized"
        
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
                    username = user.get("name", "")
                    user_id = user.get("id", "")
                    
                    # Get profile information
                    profile = user.get("profile", {})
                    display_name = profile.get("display_name", "")
                    real_name = profile.get("real_name", "")
                    first_name = profile.get("first_name", "")
                    
                    # Create comprehensive user object
                    user_data = {
                        "id": user_id,
                        "username": username,
                        "display_name": display_name,
                        "real_name": real_name,
                        "first_name": first_name
                    }
                    
                    # Use username as the key, but store full user data
                    if username.lower() not in current_config["users"]:
                        current_config["users"][username.lower()] = user_data
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
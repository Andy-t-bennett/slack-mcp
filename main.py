import sys
import ssl
import certifi
import yaml
import os
import datetime
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

####### MCP TOOLS #######

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
def send_message_to_user(user_names: list[str], message: str) -> str:
    """
    Send a direct message to one or more users in Slack. Creates a group conversation if multiple users are specified.
    
    Args:
        user_names: List of user names to send the message to (e.g., ["andy"], ["andy", "alec"])
        message: The text content of the message to send
        
    Returns:
        str: A confirmation message if successful, or an error message if the send failed
    """
    try:
        # Check if client is initialized
        if client is None:
            return "Slack not configured. Please ask me to setup slack and provide your user token."
        
        # Validate input
        if not user_names or len(user_names) == 0:
            return "Error: At least one user name must be provided"
        
        # Look up all user IDs
        user_ids = []
        for user_name in user_names:
            user_id = _get_slack_user(user_name)
            if user_id is None:
                return f"Error: User '{user_name}' not found in config"
            user_ids.append(user_id)
        
        # Handle single user (direct message)
        if len(user_ids) == 1:
            response = client.chat_postMessage(
                channel=user_ids[0],
                text=message
            )
            
            if response["ok"]:
                return f"Direct message sent successfully to {user_names[0]}!"
            else:
                return f"Error: {response['error']}"
        
        # Handle multiple users (group message)
        else:
            # Create or open a group conversation
            response = client.conversations_open(users=user_ids)
            
            if not response["ok"]:
                return f"Error creating group conversation: {response['error']}"
            
            group_channel_id = response["channel"]["id"]
            
            # Send message to the group
            response = client.chat_postMessage(
                channel=group_channel_id,
                text=message
            )
            
            if response["ok"]:
                user_list = ", ".join(user_names)
                return f"Group message sent successfully to {user_list}!"
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

@mcp.tool()
def get_my_messages(limit: int = 20) -> str:
    """
    Get all my recent messages - both direct/group messages and channel mentions.

    Args:
        limit: Number of recent messages to retrieve (default: 20, max: 100)
        
    Returns:
        str: A formatted list of all messages directed at me with timestamps and context
    """
    try:
        # Check if client is initialized
        if client is None:
            return "Slack not configured. Please ask me to setup slack and provide your user token."
        
        # Get current user info
        auth_response = client.auth_test()
        if not auth_response["ok"]:
            return f"Error getting user info: {auth_response.get('error', 'Unknown error')}"

        current_user_id = auth_response["user_id"]
        
        # Limit the number of results (max 100 for safety)
        limit = min(limit, 100)
        
        # Get direct/group messages first
        dm_results = _get_direct_and_group_messages(current_user_id, limit)
        
        # Get channel mentions
        channel_results = _get_channel_mentions(current_user_id, limit)
        
        # Combine results
        final_output = []
        
        if dm_results:
            final_output.append("=== DIRECT & GROUP MESSAGES ===")
            final_output.append(dm_results)
        
        if channel_results:
            if final_output:  # Add separator if we have DM results
                final_output.append("\n=== CHANNEL MENTIONS ===")
            else:
                final_output.append("=== CHANNEL MENTIONS ===")
            final_output.append(channel_results)
        
        if not final_output:
            return "No recent messages found."
        
        return "\n".join(final_output)
        
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def update_slack_status(
    status_text: str = "",
    status_emoji: str = "",
    presence: str = "",
    expiration_minutes: int = 0
) -> str:
    """
    Update your Slack status and presence in one go - the ultimate Slack status function!
    
    Args:
        status_text: Status message (e.g., "In a meeting", "Walking the dog", "Reading PRs")
        status_emoji: Status emoji (e.g., ":coffee:", ":dog:", ":books:", ":calendar:")
        presence: Your availability - "online", "away", or "" (no change)
        expiration_minutes: Minutes until status expires (0 = no expiration, max 1440 = 24 hours)
        
    Examples:
        update_slack_status("Walking the dog", ":dog:", "away", 30)  # Away with dog status for 30 mins
        update_slack_status("", "", "away")  # Just go away/offline
        update_slack_status("Reading PRs", ":books:")  # Status with emoji, stay online
        update_slack_status("In a meeting", ":calendar:", "online", 60)  # Busy but available
        
    Returns:
        str: A confirmation message with what was updated
    """
    try:
        # Check if client is initialized
        if client is None:
            return "Slack not configured. Please ask me to setup slack and provide your user token."
        
        results = []
        
        # Handle status update (text + emoji + expiration)
        # Update status if we have content OR if we're explicitly clearing (empty text/emoji provided)
        has_status_content = status_text or status_emoji or expiration_minutes > 0
        explicitly_clearing = (status_text == "" or status_emoji == "") and presence  # Clearing status while setting presence
        
        if has_status_content or explicitly_clearing:
            # Limit expiration to 24 hours max
            if expiration_minutes > 1440:
                expiration_minutes = 1440
            
            # Calculate expiration timestamp if specified
            expiration = 0
            if expiration_minutes > 0:
                import time
                expiration = int(time.time()) + (expiration_minutes * 60)
            
            # Prepare the profile update
            profile_data = {
                "status_text": status_text,
                "status_emoji": status_emoji
            }
            
            # Add expiration if specified
            if expiration > 0:
                profile_data["status_expiration"] = expiration
            
            # Update the user's profile
            response = client.users_profile_set(profile=profile_data)
            
            if response["ok"]:
                # Format the status confirmation
                status_parts = []
                if status_emoji:
                    status_parts.append(f"Emoji: {status_emoji}")
                if status_text:
                    status_parts.append(f"Text: '{status_text}'")
                
                if status_parts:
                    status_description = " | ".join(status_parts)
                    
                    expiration_text = ""
                    if expiration_minutes > 0:
                        if expiration_minutes < 60:
                            expiration_text = f" (expires in {expiration_minutes} minutes)"
                        else:
                            hours = expiration_minutes // 60
                            minutes = expiration_minutes % 60
                            if minutes > 0:
                                expiration_text = f" (expires in {hours}h {minutes}m)"
                            else:
                                expiration_text = f" (expires in {hours} hours)"
                    
                    results.append(f"✅ Status updated: {status_description}{expiration_text}")
                else:
                    results.append("✅ Status cleared")
            else:
                results.append(f"❌ Status update failed: {response.get('error', 'Unknown error')}")
        
        # Handle presence update (online/away)
        if presence:
            # Validate and normalize presence
            if presence.lower() in ["online", "auto"]:
                presence_value = "auto"
                presence_display = "ONLINE"
            elif presence.lower() == "away":
                presence_value = "away"
                presence_display = "AWAY (offline)"
            else:
                results.append(f"❌ Invalid presence '{presence}'. Use 'online' or 'away'")
                presence_value = None
            
            if presence_value:
                response = client.users_setPresence(presence=presence_value)
                
                if response["ok"]:
                    if presence_value == "away":
                        results.append("✅ Presence set to AWAY (offline) - green dot hidden")
                    else:
                        results.append("✅ Presence set to ONLINE - green dot visible")
                else:
                    results.append(f"❌ Presence update failed: {response.get('error', 'Unknown error')}")
        
        # Return combined results
        if results:
            return "\n".join(results)
        else:
            return "No changes requested. Specify status_text, status_emoji, presence, or expiration_minutes."
            
    except Exception as e:
        return f"Error: {str(e)}"

####### HELPER FUNCTIONS #######

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

def _get_from_user_from_id(user_id: str, config: dict) -> str:
    """
    Get user who sent the message from user ID using the config data.
    
    Args:
        user_id: The Slack user ID to look up
        config: The loaded config dictionary
        
    Returns:
        str: The user who sent the message if found, or the user ID if not found
    """
    if "users" not in config:
        return user_id
    
    for user_data in config["users"].values():
        if user_data.get("id") == user_id:
            # Return the best available name
            return (user_data.get("display_name") or 
                   user_data.get("real_name") or 
                   user_data.get("username") or 
                   user_id)
    
    return user_id

def _get_direct_and_group_messages(current_user_id: str, limit: int) -> str:
    """
    Get direct messages and group messages directed at the user.
    
    Args:
        current_user_id: The current user's Slack ID
        limit: Maximum number of messages to retrieve
        
    Returns:
        str: Formatted string of direct and group messages, or None if no messages found
    """
    try:
        # Get all DM and group conversations with updated scopes
        conversations_response = client.conversations_list(
            types="im,mpim,private_channel",
            exclude_archived=True
        )
        
        if not conversations_response["ok"]:
            return None
        
        # Reload config to get user info
        with open(config_path, 'r') as file:
            current_config = yaml.safe_load(file)
        
        all_messages = []
        
        for conversation in conversations_response["channels"]:
            conv_id = conversation["id"]
            conv_type = conversation.get("is_im", False)
            is_group = conversation.get("is_mpim", False)
            is_private_channel = conversation.get("is_private", False)
            
            # Process direct messages, group DMs, and private channels
            if not (conv_type or is_group or is_private_channel):
                continue
            
            # Get recent messages from this conversation
            history_response = client.conversations_history(
                channel=conv_id,
                limit=min(limit, 20)  # Get up to 20 messages per conversation
            )
            
            if history_response["ok"]:
                messages = history_response.get("messages", [])
                
                for message in messages:
                    # Skip messages from the current user (we want messages TO us, not FROM us)
                    if message.get("user") == current_user_id:
                        continue
                    
                    # Skip bot messages and system messages
                    if message.get("bot_id") or message.get("subtype"):
                        continue
                    
                    # Format timestamp
                    timestamp = message.get("ts", "")
                    if timestamp:
                        dt = datetime.datetime.fromtimestamp(float(timestamp))
                        time_str = dt.strftime("%H:%M:%S")
                    else:
                        time_str = "Unknown time"
                    
                    # Get sender name
                    sender_id = message.get("user", "")
                    sender_name = _get_from_user_from_id(sender_id, current_config)
                    
                    # Get message text
                    text = message.get("text", "")
                    
                    # Determine conversation context
                    if conv_type:  # Direct message
                        context = "Direct Message"
                    elif is_group:  # Group DM
                        # Get all members of the group
                        members_response = client.conversations_members(channel=conv_id)
                        if members_response["ok"]:
                            member_ids = members_response["members"]
                            member_names = []
                            for member_id in member_ids:
                                if member_id != current_user_id:  # Exclude ourselves
                                    member_name = _get_from_user_from_id(member_id, current_config)
                                    member_names.append(member_name)
                            context = f"Group: [{', '.join(member_names)}]"
                        else:
                            context = "Group DM"
                    elif is_private_channel:  # Private channel
                        channel_name = conversation.get("name", "Unknown Channel")
                        context = f"Private Channel: #{channel_name}"
                    else:
                        context = "Unknown"
                    
                    all_messages.append({
                        "timestamp": float(timestamp) if timestamp else 0,
                        "time_str": time_str,
                        "sender": sender_name,
                        "text": text,
                        "context": context
                    })
        
        if not all_messages:
            return None
        
        # Sort messages by timestamp (newest first)
        all_messages.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Limit to requested number of messages
        all_messages = all_messages[:limit]
        
        # Group messages by context and format output
        contexts = {}
        for msg in all_messages:
            context = msg["context"]
            if context not in contexts:
                contexts[context] = []
            contexts[context].append(f"[{msg['time_str']}] {msg['sender']}: {msg['text']}")
        
        # Format the final output
        formatted_output = []
        for context, messages in contexts.items():
            formatted_output.append(f"\n{context}:")
            formatted_output.extend(messages)
        
        return "\n".join(formatted_output)
        
    except Exception as e:
        return None

def _get_channel_mentions(current_user_id: str, limit: int) -> str:
    """
    Get channel mentions directed at the user.
    
    Args:
        current_user_id: The current user's Slack ID
        limit: Maximum number of messages to retrieve
        
    Returns:
        str: Formatted string of channel mentions, or None if no messages found
    """
    try:
        # query messages from @USER_ID
        response = client.search_messages(
            query=f"<@{current_user_id}>",
            count=limit,
            sort="timestamp",
            sort_dir="desc"
        )

        if response["ok"]:
            matches = response.get("messages", {}).get("matches", [])
            if len(matches) > 0:
                # Reload config to get channel/user info
                with open(config_path, 'r') as file:
                    current_config = yaml.safe_load(file)

                # Group messages by channel
                channels = {}
                for match in matches:
                    channel_name = match["channel"]["name"]
                    if channel_name not in channels:
                        channels[channel_name] = []
                    
                    # Format timestamp
                    timestamp = match.get("ts", "")
                    if timestamp:
                        dt = datetime.datetime.fromtimestamp(float(timestamp))
                        time_str = dt.strftime("%H:%M:%S")
                    else:
                        time_str = "Unknown time"
                    
                    # Get user who sent the message
                    from_user = _get_from_user_from_id(match["user"], current_config)
                    
                    # Clean up the message text by removing the mention format
                    text = match["text"]
                    # Remove the <@UUID|Username> format
                    text = text.replace(f"<@{current_user_id}|Indie Builds>", "").strip()
                    
                    channels[channel_name].append(f"[{time_str}] {from_user}: {text}")

                # Format the final output
                formatted_output = []
                for channel, messages in channels.items():
                    formatted_output.append(f"\nIn #{channel}:")
                    formatted_output.extend(messages)
                
                return "\n".join(formatted_output)
            else:
                return None
        else:  
            return None
    except Exception as e:
        return None

if __name__ == "__main__":
    mcp.run()
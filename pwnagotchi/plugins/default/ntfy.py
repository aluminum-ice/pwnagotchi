import pwnagotchi.plugins as plugins
import requests
import logging
import base64

API_ENDPOINT = "http://127.0.0.1:8666/api/v1/inbox/"

class ntfy(plugins.Plugin):
    __author__ = "retiolus"
    __version__ = '1.4.1'
    __license__ = 'GPL3'
    __description__ = '''A plugin for Pwnagotchi to send notifications and alerts to devices via ntfy service.
                    Don't forget to add the following options in your config (token, priority and icon are optional):
                    main.plugins.ntfy.enabled = true
                    main.plugins.ntfy.name = 'pwnagotchi'
                    main.plugins.ntfy.serverlink = 'https://ntfy.sh/yourntfylink'
                    main.plugins.ntfy.token = 'tk_yourntfytoken'
                    main.plugins.ntfy.priority = '3'
                    main.plugins.ntfy.icon = 'https://files.catbox.moe/1toze0.jpg'
                    Enjoy!'''
        
    def on_loaded(self):
        try:
            self.name = self.options.get('name', 'pwnagotchi')
            self.serverlink = self.options['serverlink']
            self.token = self.options.get('token', None)
            self.priority = self.options.get('priority', '3')
            self.icon = self.options.get('icon', 'https://files.catbox.moe/1toze0.jpg')
            self.picture = '/root/pwnagotchi.png'

            self.internet_notification_sent = False
            self.unread_notification_sent = False
            self.prev_unread_count = 0
            self.last_seen_msg_id = 0
            
            logging.info(f"[ntfy] Plugin initialized with device name: '{self.name}' and server URL: {self.serverlink}")
        except Exception as e:
            logging.error(f"[ntfy] An issue occurred during plugin initialization: {str(e)}")

    def send_notification(self, title_text, message_text, file_path=None, tags=None, actions=None):
        headers = {}
        headers["Title"] = title_text.encode(encoding='utf-8')
        headers["Priority"] = str(self.priority)
        headers['Icon'] = self.icon

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if tags:
            headers["Tags"] = tags

        if actions:
            headers["Actions"] = actions
            
        if file_path:
            with open(file_path, 'rb') as file_data:
                data = file_data
                headers["Filename"] = file_path.split('/')[-1]
                response = requests.put(self.serverlink, data=data, headers=headers)
        else:
            data = message_text.encode(encoding='utf-8')
            response = requests.post(self.serverlink, data=data, headers=headers)

        try:        
            if response.status_code == 200:
                logging.info(f"[ntfy] Notification sent successfully: '{message_text}'")
                return True
            else:
                logging.warning(f"[ntfy] Server responded with status code: {response.status_code}. Message might not have been delivered.")
                return False
        except requests.RequestException as e:
            logging.error(f"[ntfy] Failed to send notification due to: {e}")
            return False

    def check_and_notify_unseen_messages(self):
        try:
            response = requests.get(API_ENDPOINT)
            if response.status_code == 200:
                data = response.json()
                for message in data["messages"]:
                    if message["seen_at"] is None and message["id"] > self.last_seen_msg_id:
                        msg_content_response = requests.get(f"{API_ENDPOINT}{message['id']}")
                        if msg_content_response.status_code == 200:
                            msg_data = msg_content_response.json()
                            decoded_content = base64.b64decode(msg_data["data"]).decode('utf-8')
                            self.send_notification(title_text=f"New message from {message['sender_name']}", 
                                                   message_text=decoded_content,
                                                   tags="envelope")
                            self.last_seen_msg_id = max(self.last_seen_msg_id, message["id"])
        except Exception as e:
            logging.error(f"[ntfy] Error while checking and notifying for unseen messages: {str(e)}")

    # TODO: add on_internet_not_available self.internet_notification_sent = False
    def on_internet_available(self, agent):
        self.check_and_notify_unseen_messages()
        config = agent.config()
        self.handshakes_dir = config['bettercap']['handshakes']

        if not self.internet_notification_sent:
            title = self.options.get('on_internet_available_title', '{self.name}').format(**locals())
            message = self.options.get('on_internet_available_msg', 'Congratulations! Your {self.name} is now connected to the Internet.').format(**locals())
            tags = self.options.get('on_internet_available_tags', 'rotating_light')
            success = self.send_notification(title_text=title, message_text=message, tags=tags)
            if success:
                self.internet_notification_sent = True
  
    def on_handshake(self, agent, filename, access_point, client_station):
        message = self.options.get('on_handshake_msg', 'Your {self.name} has captured a new handshake from {client_station[mac]} (Client) via {access_point[mac]} (Access Point).').format(**locals())
        title = self.options.get('on_handshake_title', '{message}').format(**locals())
        tags = self.options.get('on_handshake_tags', 'triangular_flag_on_post')
        # save_button = f"http, save, {self.serverlink}/{filename}"
        wigle_button = f"view, wigle.net, https://wigle.net/search?netid={access_point['mac']}"
        actions = f"{wigle_button}"
        self.send_notification(title_text=title, message_text=message, file_path=filename, tags=tags, actions=actions)

    def on_peer_lost(self, agent, peer):
        title = self.options.get('on_peer_lost_title', '{self.name}').format(**locals())
        message = self.options.get('on_peer_lost_msg', 'Your {self.name} lost connection with peer: {peer.name}.').format(**locals())
        tags = self.options.get('on_peer_lost_tags', 'broken_heart')
        self.send_notification(title_text=title, message_text=message, tags=tags)

    # TODO

    # ISN'T ON_NEW_PEER = ON_PEER_DETECTED ?
    # def on_new_peer(self, peer):
    #     pass
    
    # def on_uploading(self, to):
    #     pass

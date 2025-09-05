from typing import Dict

class PodHomeEpisode:
    def __init__(self, episode: Dict):
        self.episode_id = episode.get('episode_id', '1')
        self.episode_nr = int(episode.get('episode_nr', '1'))
        self.title = episode.get('title', '')
        self.description = episode.get('description', '')
        self.status = int(episode.get('status', '0'))
        self.publish_date = episode.get('publish_date', '')
        self.duration = episode.get('duration', '')
        self.enclosure_url = episode.get('enclosure_url', '')
        self.season_nr = int(episode.get('season_nr', '1'))
        self.image_url = episode.get('image_url', '')
        self.link = episode.get('link', '')
    
    def setPublishdate(self, publishDate: str):
        self.publish_date = publishDate

class Episode:
    def __init__(self, episode: Dict):
        self.episode_id = episode[0].get('episode_id', '')
        self.episode_nr = int(episode[0].get('episode_nr', '1'))
        self.title = episode[0].get('title', '')
        self.description = episode[0].get('description', '')
        self.status = int(episode[0].get('status', '0'))
        self.publish_date = episode[0].get('publish_date', '')
        self.duration = episode[0].get('duration', '')
        self.enclosure_url = episode[0].get('enclosure_url', '')
        self.season_nr = int(episode[0].get('season_nr', '1'))
        self.link = episode[0].get('link', '')
        self.image_url = episode[0].get('image_url', '')
        self.donations = int(episode[0].get('donations', '0'))

class AlbyWalletBalance:
    def __init__(self, wallet_balance: Dict):
        self.balance = int(wallet_balance.get('balance', ''))
        self.unit = wallet_balance.get('unit', '')
        self.currency = wallet_balance.get('currency', '')
import re
import requests


class VKMethods:
    def __init__(self, logger, token=None):
        self.token = token
        self.logger = logger

    async def like_vk_post(self, url):
        self.logger.info('Лайкаю пост..')
        if 'vk.com' not in url:
            return 0
        group = '-' in url
        if 'wall' in url:
            type = 'post'
        elif 'video' in url:
            type = 'video'
        elif 'photo' in url:
            type = 'photo'
        elif 'audio' in url:
            type = 'audio'
        elif 'note' in url:
            type = 'note'
        elif 'market' in url:
            type = 'market'
        elif 'photo_comment' in url:
            type = 'photo_comment'
        elif 'video_comment' in url:
            type = 'video_comment'
        elif 'topic_comment' in url:
            type = 'topic_comment'
        elif 'market_comment' in url:
            type = 'market_comment'
        elif 'clip' in url:
            type = 'clip'
        url = url.replace('https://vk.com/', '').split('_')
        owner_id = re.findall('\\d+', url[0])[0]
        if group:
            owner_id = '-' + owner_id
        post_id = re.findall('\\d+', url[1])[0]
        response = requests.get(
            'https://'
            'api.vk.com/method/likes.add'
            f'?type={type}'
            f'&owner_id={owner_id}'
            f'&item_id={post_id}'
            f'&access_token={self.token}'
            '&v=5.131'
        )
        self.logger.info(f'Ответ вк: {response.json()}')
        if response.json().get('response').get('likes'):
            return 1
        return 0

    async def join_vk_group(self, url):
        self.logger.info('Присоединяюсь к группе..')
        if 'vk.com' not in url:
            return 0
        group_id = url.split('/')[-1].replace('club', '')
        response = requests.get(
            'https://api.vk.com/method/groups.join'
            f'?group_id={group_id}'
            f'&access_token={self.token}'
            '&v=5.131'
        )
        self.logger.info(f'Ответ вк: {response.json()}')
        if response.json().get('response') == 1:
            return 1
        return 0

    async def add_vk_friend(self, url):
        self.logger.info('Добавляю в друзья')
        if 'vk.com' not in url:
            return 0
        user_id = url.split('/')[-1].replace('id', '')
        response = requests.get(
            'https://api.vk.com/method/friends.add'
            f'?user_id={user_id}'
            f'&access_token={self.token}'
            '&v=5.131'
        )
        self.logger.info(f'Ответ ВК: {response.json()}')
        if response.json().get('response') == 1:
            return 1
        return 0

    async def get_vk_post(self, url):
        self.logger.info('Получаю информацию о посте')
        if 'vk.com' not in url:
            return 0
        post_id = url.split('_')[-1]
        response = requests.get(
            'https://api.vk.com/method/wall.getById'
            f'?posts={post_id}'
            f'&access_token={self.token}'
            '&v=5.131'
        )
        self.logger.info(f'Ответ ВК: {response.json()}')
        if 'response' in response.json():
            return 1
        return 0

"""Turnstile verification helper (keeps original API)."""
import os
import time
import requests


class TurnstileService:
    def __init__(self, solver_url="http://127.0.0.1:5072", proxies=None):
        self.yescaptcha_key = os.getenv('YESCAPTCHA_KEY', '').strip()
        self.solver_url = solver_url
        self.yescaptcha_api = "https://api.yescaptcha.com"
        self.proxies = proxies or {}

    def create_task(self, siteurl, sitekey):
        if self.yescaptcha_key:
            url = f"{self.yescaptcha_api}/createTask"
            payload = {
                "clientKey": self.yescaptcha_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": siteurl,
                    "websiteKey": sitekey
                }
            }
            response = requests.post(url, json=payload, proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            if data.get('errorId') != 0:
                raise Exception(f"YesCaptcha创建任务失败: {data.get('errorDescription')}")
            return data['taskId']
        else:
            url = f"{self.solver_url}/turnstile?url={siteurl}&sitekey={sitekey}"
            response = requests.get(url, proxies=self.proxies)
            response.raise_for_status()
            return response.json()['taskId']

    def get_response(self, task_id, max_retries=30, initial_delay=5, retry_delay=2):
        time.sleep(initial_delay)
        for _ in range(max_retries):
            try:
                if self.yescaptcha_key:
                    url = f"{self.yescaptcha_api}/getTaskResult"
                    payload = {"clientKey": self.yescaptcha_key, "taskId": task_id}
                    response = requests.post(url, json=payload, proxies=self.proxies)
                    response.raise_for_status()
                    data = response.json()
                    if data.get('errorId') != 0:
                        return None
                    if data.get('status') == 'ready':
                        return data.get('solution', {}).get('token')
                    time.sleep(retry_delay)
                else:
                    url = f"{self.solver_url}/result?id={task_id}"
                    response = requests.get(url, proxies=self.proxies)
                    response.raise_for_status()
                    data = response.json()
                    captcha = data.get('solution', {}).get('token', None)
                    if captcha and captcha != "CAPTCHA_FAIL":
                        return captcha
                    time.sleep(retry_delay)
            except Exception as e:
                print(f"获取Turnstile响应异常: {e}")
                time.sleep(retry_delay)
        return None

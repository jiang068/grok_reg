"""freemail 客户端，放在 services 子包下。"""
import os
import re
import time
import uuid
from typing import Optional, Tuple

import requests


class EmailService:
    """Minimal, robust freemail client.

    支持常见 freemail worker API。
    """

    def __init__(self, proxies=None):
        # Only read the canonical env names: WORKER_DOMAIN and FREEMAIL_TOKEN
        worker_domain = (os.getenv("WORKER_DOMAIN") or "").strip().rstrip("/")
        token = (os.getenv("FREEMAIL_TOKEN") or "").strip()
        if not worker_domain or not token:
            raise ValueError("缺少 freemail 配置：请在 grok_reg/.env 或环境变量中设置 WORKER_DOMAIN 和 FREEMAIL_TOKEN")

        self.base_url = f"https://{worker_domain}"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.proxies = proxies or {}

    def create_email(self) -> Tuple[str, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/generate", headers=self.headers, proxies=self.proxies, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                email = data.get("email") or data.get("address")
                if email:
                    return email, email
        except Exception:
            pass

        username = uuid.uuid4().hex[:8]
        try:
            resp = requests.post(f"{self.base_url}/mailbox", json={"name": username}, headers=self.headers, proxies=self.proxies, timeout=10)
            if resp.status_code in (200, 201):
                data = resp.json()
                email = data.get("email") or data.get("address") or data.get("name")
                mailbox = data.get("mailbox") or data.get("id") or (email or username)
                if email:
                    return email, mailbox
        except Exception:
            pass

        try:
            resp = requests.get(f"{self.base_url}/mailbox", params={"name": username}, headers=self.headers, proxies=self.proxies, timeout=10)
            if resp.status_code in (200, 201):
                data = resp.json()
                email = data.get("email") or data.get("address") or data.get("name")
                mailbox = data.get("mailbox") or data.get("id") or (email or username)
                if email:
                    return email, mailbox
        except Exception:
            pass

        return "", ""

    def fetch_verification_code(self, mailbox: str, max_attempts: int = 1, debug: bool = False) -> Optional[str]:
        if debug:
            print(f"[EmailService] 轮询验证码 mailbox={mailbox} attempts={max_attempts}")
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(1)
            try:
                try:
                    resp = requests.get(f"{self.base_url}/api/emails", params={"mailbox": mailbox}, headers=self.headers, proxies=self.proxies, timeout=10)
                    if resp.status_code == 200:
                        items = resp.json()
                        if items:
                            first = items[0]
                            code = first.get("verification_code") or first.get("code") or first.get("verify_code")
                            if code:
                                return str(code).replace('-', '')
                            subject = first.get("subject", "")
                            m = re.search(r'\b([A-Z0-9]{2,4}-[A-Z0-9]{2,4})\b', subject)
                            if m:
                                return m.group(1).replace('-', '')
                except Exception:
                    pass

                try:
                    resp = requests.get(f"{self.base_url}/mailbox/{mailbox}/messages", headers=self.headers, proxies=self.proxies, timeout=10)
                    if resp.status_code == 200:
                        msgs = resp.json()
                        if msgs:
                            msg = msgs[0] if isinstance(msgs, list) else msgs
                            code = msg.get("verification_code") if isinstance(msg, dict) else None
                            if not code:
                                subj = msg.get("subject", "") if isinstance(msg, dict) else ""
                                m = re.search(r'\b([A-Z0-9]{2,4}-[A-Z0-9]{2,4})\b', subj)
                                if m:
                                    code = m.group(1).replace('-', '')
                            if not code:
                                body = msg.get("body") or msg.get("preview") or "" if isinstance(msg, dict) else ""
                                m6 = re.search(r'\b(\d{6})\b', body)
                                if m6:
                                    code = m6.group(1)
                            if code:
                                return str(code)
                except Exception:
                    pass
            except Exception:
                pass
        return None

    def delete_mailbox(self, email: str) -> None:
        try:
            mailbox = email.split("@")[0] if "@" in email else email
            try:
                requests.delete(f"{self.base_url}/api/mailboxes", params={"address": email}, headers=self.headers, proxies=self.proxies, timeout=6)
            except Exception:
                pass
            try:
                requests.delete(f"{self.base_url}/mailbox/{mailbox}", headers=self.headers, proxies=self.proxies, timeout=6)
            except Exception:
                pass
        except Exception:
            pass

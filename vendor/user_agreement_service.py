"""User agreement helper adapted from original vendor module."""
import os
from typing import Optional, Dict, Any
import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class UserAgreementService:
    def __init__(self, cf_clearance: str = ""):
        self.cf_clearance = (cf_clearance or "").strip()

    def accept_tos_version(
        self,
        sso: str,
        sso_rw: str,
        impersonate: str,
        user_agent: Optional[str] = None,
        cf_clearance: Optional[str] = None,
        timeout: int = 15,
        proxies: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not sso:
            return {"ok": False, "hex_reply": "", "status_code": None,
                    "grpc_status": None, "error": "缺少 sso"}
        if not sso_rw:
            return {"ok": False, "hex_reply": "", "status_code": None,
                    "grpc_status": None, "error": "缺少 sso-rw"}

        url = "https://accounts.x.ai/auth_mgmt.AuthManagement/SetTosAcceptedVersion"
        cookies = {"sso": sso, "sso-rw": sso_rw}
        clearance = (cf_clearance if cf_clearance is not None else self.cf_clearance).strip()
        if clearance:
            cookies["cf_clearance"] = clearance

        headers = {
            "content-type": "application/grpc-web+proto",
            "origin": "https://accounts.x.ai",
            "referer": "https://accounts.x.ai/accept-tos",
            "x-grpc-web": "1",
            "user-agent": user_agent or DEFAULT_USER_AGENT,
        }
        data = b"\x00\x00\x00\x00\x02\x10\x01"

        try:
            response = requests.post(
                url,
                headers=headers,
                cookies=cookies,
                data=data,
                timeout=timeout,
                proxies=proxies or {},
            )
            hex_reply = response.content.hex()
            grpc_status = response.headers.get("grpc-status")
            error = None
            ok = response.status_code == 200 and (grpc_status in (None, "0"))
            if response.status_code == 403:
                error = "403 Forbidden"
            elif response.status_code != 200:
                error = f"HTTP {response.status_code}"
            elif grpc_status not in (None, "0"):
                error = f"gRPC {grpc_status}"
            return {
                "ok": ok,
                "hex_reply": hex_reply,
                "status_code": response.status_code,
                "grpc_status": grpc_status,
                "error": error,
            }
        except Exception as e:
            return {"ok": False, "hex_reply": "", "status_code": None,
                    "grpc_status": None, "error": str(e)}

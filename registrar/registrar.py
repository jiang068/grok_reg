# Registrar implementation moved into grok_reg.registrar package.

import os
import csv
import time
import asyncio
import random
import re
from datetime import datetime
from typing import List


try:
    import patchright
except Exception:
    patchright = None

# relative imports into package
# 不使用外部 TurnstileAPIServer（避免依赖外部浏览器池），强制使用本地 camoufox
ExternalTurnstileServer = None
from ..config import config
from ..services.email_service import EmailService

try:
    from ..vendor.turnstile_service import TurnstileService
except Exception:
    TurnstileService = None

try:
    from ..vendor.user_agreement_service import UserAgreementService
except Exception:
    UserAgreementService = None


class Registrar:
    def __init__(self, threads: int = None, proxy: str = None):
        self.threads = threads or config.THREADS
        self.proxy = proxy or config.PROXY
        self.output_dir = config.OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        self.email_service = EmailService(proxies=proxies)
        try:
            if patchright:
                if hasattr(patchright, 'apply_patch'):
                    patchright.apply_patch()
                elif hasattr(patchright, 'patch_playwright'):
                    patchright.patch_playwright()
                elif hasattr(patchright, 'stealth'):
                    patchright.stealth()
                if config.DEBUG:
                    print('[grok_reg] patchright 已导入并尝试应用补丁')
        except Exception as e:
            if config.DEBUG:
                print(f'[grok_reg] patchright 调用补丁失败: {e}')

        self.external_solver = None

    async def _init_external_solver(self):
        if ExternalTurnstileServer is None:
            return
        try:
            solver = ExternalTurnstileServer(
                headless=False,
                useragent=None,
                debug=config.DEBUG,
                browser_type=config.BROWSER_TYPE,
                thread=self.threads,
                proxy_support=bool(self.proxy),
                use_random_config=False,
                browser_name=None,
                browser_version=None,
                manual=True,
            )
            await solver._initialize_browser()
            self.external_solver = solver
            if config.DEBUG:
                print('[grok_reg] 已初始化 TurnstileAPIServer 浏览器池')
        except Exception as e:
            if config.DEBUG:
                print(f'[grok_reg] 初始化外部 TurnstileAPIServer 失败，回退本地实现: {e}')

    async def _extract_token(self, context, page, listen_timeout: int = 8) -> str:
        result = {"sso": "", "sso-rw": "", "jwt": ""}
        try:
            cookies = await context.cookies()
            for c in cookies:
                name = c.get('name', '').lower()
                if name == 'sso':
                    result['sso'] = c.get('value')
                if name == 'sso-rw' or name == 'sso_rw':
                    result['sso-rw'] = c.get('value')
        except Exception:
            pass

        try:
            local = await page.evaluate("() => Object.fromEntries(Object.entries(window.localStorage))")
            for k, v in local.items():
                kl = k.lower()
                if 'sso' in kl and not result['sso']:
                    result['sso'] = v
                if 'sso-rw' in kl and not result['sso-rw']:
                    result['sso-rw'] = v
                if isinstance(v, str) and not result['jwt']:
                    m_j = re.search(r"(eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})", v)
                    if m_j:
                        result['jwt'] = m_j.group(1)
        except Exception:
            pass

        try:
            sess = await page.evaluate("() => Object.fromEntries(Object.entries(window.sessionStorage))")
            for k, v in sess.items():
                kl = k.lower()
                if 'sso' in kl and not result['sso']:
                    result['sso'] = v
                if 'sso-rw' in kl and not result['sso-rw']:
                    result['sso-rw'] = v
                if isinstance(v, str) and re.search(r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}", v) and not result['jwt']:
                    result['jwt'] = v
        except Exception:
            pass

        try:
            loop = asyncio.get_event_loop()
            token_future = loop.create_future()

            def _on_response(resp):
                async def _read_and_search():
                    try:
                        if config.DEBUG:
                            print(f"[DEBUG][NET] Checking response from: {resp.url}")
                        try:
                            text = await resp.text()
                        except Exception:
                            text = ''

                        m = re.search(r"(eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})", text)
                        if m:
                            if not token_future.done():
                                token_future.set_result({'jwt': m.group(1)})
                                return

                        try:
                            hdrs = resp.headers if hasattr(resp, 'headers') else {}
                            sc = hdrs.get('set-cookie') or hdrs.get('Set-Cookie')
                            if sc:
                                m2 = re.search(r"(eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})", sc)
                                if m2 and not token_future.done():
                                    token_future.set_result({'jwt': m2.group(1)})
                                    return
                                m_s = re.search(r"(?:sso|sso[-_]rw)=([^;\s]{8,})", sc, re.IGNORECASE)
                                if m_s and not token_future.done():
                                    token_future.set_result({'sso': m_s.group(1)})
                                    return
                        except Exception:
                            pass

                        m_sso = re.search(r'"sso"\s*:\s*"([^"]{8,})"', text, re.IGNORECASE)
                        if m_sso:
                            if not token_future.done():
                                token_future.set_result({'sso': m_sso.group(1)})
                                return

                        m_sso_rw = re.search(r'"sso[-_]rw"\s*:\s*"([^"]{8,})"', text, re.IGNORECASE)
                        if m_sso_rw:
                            if not token_future.done():
                                token_future.set_result({'sso-rw': m_sso_rw.group(1)})
                                return

                        m_token = re.search(r'"access_token"\s*:\s*"([^"]{8,})"', text, re.IGNORECASE)
                        if m_token:
                            if not token_future.done():
                                token_future.set_result({'jwt': m_token.group(1)})
                                return

                        m_token2 = re.search(r'"token"\s*:\s*"([^\"]{8,})"', text, re.IGNORECASE)
                        if m_token2:
                            if not token_future.done():
                                token_future.set_result({'jwt': m_token2.group(1)})
                                return
                    except Exception:
                        pass

                asyncio.create_task(_read_and_search())

            page.on('response', _on_response)

            try:
                token_obj = await asyncio.wait_for(token_future, timeout=listen_timeout)
                if isinstance(token_obj, dict):
                    if token_obj.get('sso') and not result['sso']:
                        result['sso'] = token_obj.get('sso')
                    if token_obj.get('sso-rw') and not result['sso-rw']:
                        result['sso-rw'] = token_obj.get('sso-rw')
                    if token_obj.get('jwt') and not result['jwt']:
                        result['jwt'] = token_obj.get('jwt')
            except asyncio.TimeoutError:
                pass

            try:
                dc = await page.evaluate("() => document.cookie || ''")
                if isinstance(dc, str) and dc:
                    mdc_j = re.search(r"(eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})", dc)
                    if mdc_j and not result.get('jwt'):
                        result['jwt'] = mdc_j.group(1)
                    mdc_s = re.search(r"(?:sso|sso[-_]rw)=([^;\s]{8,})", dc, re.IGNORECASE)
                    if mdc_s:
                        if not result.get('sso'):
                            result['sso'] = mdc_s.group(1)
            except Exception:
                pass

            try:
                cookies = await context.cookies()
                for c in cookies:
                    name = c.get('name', '').lower()
                    val = c.get('value', '')
                    if not result.get('sso') and name == 'sso' and val:
                        result['sso'] = val
                    if not result.get('sso-rw') and (name == 'sso-rw' or name == 'sso_rw') and val:
                        result['sso-rw'] = val
                    if not result.get('jwt') and isinstance(val, str) and re.search(r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}", val):
                        result['jwt'] = val
            except Exception:
                pass
            finally:
                try:
                    page.off('response', _on_response)
                except Exception:
                    pass
        except Exception:
            pass

        return result

    def _is_cf_page(self, content: str, url: str) -> bool:
        cl = content.lower()
        has_cf = 'cloudflare' in cl or 'cf-chl' in url or 'challenge' in url
        has_challenge = (
            'just a moment' in cl
            or 'checking your browser' in cl
            or 'please wait' in cl
            or 'cf-challenge' in cl
            or 'cf_chl' in cl
            or '/cdn-cgi/challenge-platform' in cl
        )
        if 'cf-chl' in url or ('/cdn-cgi/' in url and 'challenge' in url):
            return True
        return has_cf and has_challenge

    async def _silent_wait_for_cf(self, page, poll_interval: float = 1.5, silent_timeout: float = 15.0) -> bool:
        try:
            content = await page.content()
            url = page.url
            if not self._is_cf_page(content, url):
                return True

            if config.DEBUG:
                print(f"[DEBUG] 检测到 Cloudflare，尝试静默等待自动通过（最多 {silent_timeout}s）...")

            elapsed = 0.0
            while elapsed < silent_timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                try:
                    content = await page.content()
                    url = page.url
                    if not self._is_cf_page(content, url):
                        if config.DEBUG:
                            print(f"[DEBUG] Cloudflare 已自动通过（{elapsed:.1f}s）")
                        return True
                except Exception:
                    pass

            if config.DEBUG:
                print(f"[DEBUG] Cloudflare 静默等待超时（{silent_timeout}s），需要人工介入")
            return False
        except Exception:
            return True

    async def _manual_wait_for_cf(self, page, silent_first: bool = False):
        try:
            content = await page.content()
            url = page.url
            is_cf = self._is_cf_page(content, url)
            if not is_cf:
                return

            sitekey = None
            try:
                el = page.locator('[data-sitekey]')
                if await el.count() > 0:
                    sitekey = await el.first.get_attribute('data-sitekey')
            except Exception:
                sitekey = None

            if sitekey and TurnstileService is not None:
                try:
                    ts = TurnstileService(proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None)
                    loop = asyncio.get_event_loop()
                    task_id = await loop.run_in_executor(None, ts.create_task, url, sitekey)
                    token = await loop.run_in_executor(None, ts.get_response, task_id)
                    if token:
                        try:
                            locator = page.locator('input[name="cf-turnstile-response"]')
                            if await locator.count() > 0:
                                await locator.fill(token)
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                        return
                except Exception:
                    pass

            if silent_first:
                passed = await self._silent_wait_for_cf(page, silent_timeout=20.0)
                if passed:
                    return

            # 非阻塞地请求人工介入：将任务标识加入队列，等待中央提示器确认后继续
            label = f"task-{id(page)}"
            try:
                await self._request_manual_cf(label)
            except Exception:
                # 如果中央提示器不可用，回退到原始行为以保证兼容性
                print("检测到 Cloudflare 限制，请在弹出的浏览器中完成验证（手动），完成后按回车继续...")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input, "完成 Cloudflare 验证并回到控制台后，按 Enter 继续...\n")
            await asyncio.sleep(1)
        except Exception:
            pass

    async def _cf_prompt_handler(self):
        """中央化的人工 Cloudflare 验证提示器：批量提示并唤醒等待的任务。"""
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    first = await self._cf_queue.get()
                except Exception:
                    await asyncio.sleep(0.1)
                    continue

                labels = [first]
                # 短暂等待以收集更多并发的 CF 请求，避免多次重复提示
                await asyncio.sleep(0.15)
                while not self._cf_queue.empty():
                    try:
                        labels.append(self._cf_queue.get_nowait())
                    except Exception:
                        break

                # 去重并格式化提示
                uniq = list(dict.fromkeys(labels))
                prompt = (
                    "检测到需要人工通过 Cloudflare 的浏览器实例：\n"
                    + "\n".join(uniq)
                    + "\n请在对应的浏览器窗口中完成验证，然后在此处按 Enter 继续（一次回车会继续上面列出的所有任务）。\n"
                )
                # 在线程池中运行 blocking input
                try:
                    await loop.run_in_executor(None, input, prompt)
                except Exception:
                    pass

                # 唤醒对应任务
                for lbl in uniq:
                    ev = None
                    try:
                        ev = self._cf_pending.pop(lbl, None)
                    except Exception:
                        ev = None
                    if ev is not None:
                        try:
                            ev.set()
                        except Exception:
                            pass
        except Exception:
            # 如果提示器退出，忽略并让任务使用回退的阻塞提示
            return

    async def _request_manual_cf(self, label: str, timeout: float = None):
        """向中央提示器注册一个需要人工验证的 label，并等待其被确认。"""
        if not hasattr(self, '_cf_queue') or not hasattr(self, '_cf_pending'):
            # 如果中央数据结构不存在（例如未在 run 中启动），直接阻塞等待输入以兼容旧逻辑
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, f"请为 {label} 完成 Cloudflare 验证后按 Enter...\n")
            return

        ev = asyncio.Event()
        # 注册并等待
        self._cf_pending[label] = ev
        await self._cf_queue.put(label)
        try:
            if timeout:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
            else:
                await ev.wait()
        except Exception:
            # 超时或取消时移除 pending 并抛出
            try:
                self._cf_pending.pop(label, None)
            except Exception:
                pass
            raise

    async def _fill_signup(self, page, email: str, password: str, submit: bool = False):
        filled = False
        selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id*="email"]',
        ]
        for s in selectors:
            try:
                el = page.locator(s)
                if await el.count() > 0:
                    await el.fill(email)
                    filled = True
                    break
            except Exception:
                pass

        if not filled:
            try:
                idx = await page.evaluate(r"""
                    () => {
                        const inputs = Array.from(document.querySelectorAll('input'));
                        for (let i = 0; i < inputs.length; i++) {
                            const t = inputs[i];
                            const attrs = (t.name || '') + ' ' + (t.id || '') + ' ' + (t.placeholder || '') + ' ' + (t.type || '');
                            if (/mail|email/i.test(attrs) || (t.placeholder || '').includes('@') || (t.type||'') === 'email') return i;
                        }
                        return -1;
                    }
                """)
                if isinstance(idx, int) and idx >= 0:
                    inp = page.locator('input').nth(idx)
                    if await inp.count() > 0:
                        await inp.fill(email)
                        filled = True
            except Exception:
                pass

        for s in ['input[type="password"]', 'input[name="password"]', 'input[id*="password"]']:
            try:
                el = page.locator(s)
                if await el.count() > 0:
                    await el.fill(password)
                    break
            except Exception:
                pass

        if submit:
            for btn_sel in [
                'button[type="submit"]',
                'button:has-text("Create")',
                'button:has-text("Sign up")',
                'button:has-text("注册")',
            ]:
                try:
                    btn = page.locator(btn_sel)
                    if await btn.count() > 0:
                        await btn.click()
                        return filled
                except Exception:
                    pass
            try:
                await page.keyboard.press('Enter')
                return filled
            except Exception:
                return filled

        return filled

    async def _request_verification(self, page) -> bool:
        send_selectors = [
            'button:has-text("Send code")',
            'button:has-text("Send")',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button[type="submit"]',
            'button:has-text("获取验证码")',
            'button:has-text("发送验证码")',
            'button:has-text("Verify")',
            'a:has-text("Send code")',
        ]
        for s in send_selectors:
            try:
                el = page.locator(s)
                if await el.count() > 0:
                    if config.DEBUG:
                        print(f"[DEBUG] 点击触发发送验证码的 selector={s}")
                    await el.first.click()
                    try:
                        await page.wait_for_selector('input[name="code"], input[id*="code"], input[placeholder*="code"], text=Email sent, text=Verification email sent, text=Verify', timeout=5000)
                    except Exception:
                        if config.DEBUG:
                            print("[DEBUG] 触发发送后等待验证码输入/提示超时，继续轮询")
                    await asyncio.sleep(0.3)
                    return True
            except Exception:
                pass
        try:
            inp = page.locator('input[type="email"]')
            if await inp.count() > 0:
                await inp.first.focus()
                await asyncio.sleep(0.1)
                await inp.first.evaluate('el => el.blur()')
                await asyncio.sleep(0.2)
                return True
            all_inp = page.locator('input')
            if await all_inp.count() > 0:
                await all_inp.first.focus()
                await asyncio.sleep(0.05)
                await all_inp.first.evaluate('el => el.blur()')
                await asyncio.sleep(0.1)
                return True
        except Exception:
            pass
        return False

    def _generate_name(self):
        first = [
            "Liam","Noah","Oliver","Elijah","James","William","Benjamin","Lucas","Henry","Alexander",
            "Olivia","Emma","Ava","Charlotte","Sophia","Amelia","Isabella","Mia","Evelyn","Harper",
        ]
        last = [
            "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
            "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin",
        ]
        return f"{random.choice(first)} {random.choice(last)}"

    async def _fill_verification(self, page, mailbox: str) -> bool:
        loop = asyncio.get_event_loop()

        def _fetch_once(mailbox_arg):
            try:
                return self.email_service.fetch_verification_code(mailbox_arg, 1, config.DEBUG)
            except TypeError:
                try:
                    return self.email_service.fetch_verification_code(mailbox_arg)
                except Exception:
                    return None
            except Exception:
                return None

        max_attempts = 60
        try:
            for i in range(1, max_attempts + 1):
                if config.DEBUG:
                    print(f"[DEBUG] 第 {i}/{max_attempts} 次轮询...")
                try:
                    code = await loop.run_in_executor(None, _fetch_once, mailbox)
                except asyncio.CancelledError:
                    if config.DEBUG:
                        print("[DEBUG] 验证码轮询被取消（任务中断）")
                    return False

                if code:
                    if config.DEBUG:
                        print(f"[DEBUG] 获取到验证码: {code}")
                    try:
                        for sel in ['input[name="code"]', 'input[id*="code"]', 'input[placeholder*="code"]', 'input[type="text"]']:
                            try:
                                inp = page.locator(sel)
                                if await inp.count() > 0:
                                    await inp.fill(code)
                                    await page.keyboard.press('Enter')
                                    return True
                            except Exception:
                                pass
                        digits = page.locator('input')
                        if await digits.count() > 0:
                            idx = 0
                            for j in range(min(8, await digits.count())):
                                try:
                                    d = digits.nth(j)
                                    await d.fill(code[idx:idx+1])
                                    idx += 1
                                    if idx >= len(code):
                                        break
                                except Exception:
                                    pass
                            return True
                    except Exception:
                        pass

                await asyncio.sleep(1)
            if config.DEBUG:
                print(f"[DEBUG] 未获取到验证码，{max_attempts} 次轮询结束")
            return False
        except asyncio.CancelledError:
            if config.DEBUG:
                print("[DEBUG] 验证码轮询在外部取消时优雅退出")
            return False

    async def register_task(self, index: int):
        print(f"[{index}] register_task 启动")
        ts = int(time.time())
        password = f"Xai{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}"

        browser = None
        solver = self.external_solver
        got_browser_from_pool = False
        index_bp = None
        browser_config = None
        cam_owner = None
        if solver is not None:
            try:
                print(f"[{index}] 从 external solver 浏览器池尝试获取浏览器...")
                # 不要在空的 asyncio.Queue 上无限等待；使用短超时以便回退到本地浏览器
                try:
                    index_bp, browser, browser_config = await asyncio.wait_for(solver.browser_pool.get(), timeout=1.0)
                    got_browser_from_pool = True
                    print(f"[{index}] 成功从 external 浏览器池获取浏览器: index_bp={index_bp}")
                except asyncio.TimeoutError:
                    if config.DEBUG:
                        print(f"[{index}] 从 external 浏览器池获取超时（队列可能为空），将回退本地启动")
                except Exception as e:
                    if config.DEBUG:
                        print(f"[{index}] 从外部浏览器池获取 browser 失败，回退本地启动: {e}")
            except Exception:
                # 外层异常不阻塞任务，继续回退本地启动
                if config.DEBUG:
                    print(f"[{index}] external solver 获取流程出现异常，回退本地启动")

        if browser is None:
            # 延迟导入 camoufox，避免在未安装该依赖的环境中导入失败
            try:
                print(f"[{index}] 本地启动浏览器，尝试导入 camoufox...")
                from camoufox.async_api import AsyncCamoufox
            except Exception as e:
                print(f"[{index}] 无法导入 camoufox: {e}. 请先在运行环境中安装依赖 (pip install camoufox) 或使用包含该包的虚拟环境。")
                return None

            cam_owner = AsyncCamoufox(headless=False)
            try:
                print(f"[{index}] 启动本地 Camoufox 浏览器... (headless=False)")
                browser = await cam_owner.__aenter__()
                print(f"[{index}] 本地 Camoufox 浏览器启动完成")
            except Exception as e:
                print(f"[{index}] 启动 Camoufox 失败: {e}. 请确保 camoufox 已安装或使用其它浏览器。")
                try:
                    await cam_owner.__aexit__(None, None, None)
                except Exception:
                    pass
                return None

        try:
            print(f"[{index}] 新建 browser context & page")
            context = await browser.new_context()
            page = await context.new_page()
            print(f"[{index}] 导航到 signup 页面: {config.SIGNUP_URL}")
            await page.goto(config.SIGNUP_URL, wait_until='domcontentloaded', timeout=60000)
            print(f"[{index}] page.goto 返回，当前 URL: {page.url}")

            signup_selectors = [
                'button:has-text("Sign up with email")',
                'button:has-text("Sign up with Email")',
                'button:has-text("Sign up with e-mail")',
                'button:has-text("Sign up with mail")',
                'button:has-text("Sign up with X")',
                'button:has-text("Sign up")',
                'a:has-text("Sign up")',
                'a[href*="/sign-up"]',
                'button:has-text("注册")',
            ]
            clicked_signup = False
            for sel in signup_selectors:
                try:
                    el = page.locator(sel)
                    if await el.count() > 0:
                        if config.DEBUG:
                            print(f"[DEBUG] 点击 signup 按钮，selector={sel}")
                        await el.first.click()
                        try:
                            await page.wait_for_selector(
                                'input[type="email"], input[name="email"], input[id*="email"], input',
                                timeout=5000
                            )
                        except Exception:
                            if config.DEBUG:
                                print("[DEBUG] 等待 email input 超时，继续尝试填充")
                        await asyncio.sleep(0.5)
                        clicked_signup = True
                        break
                except Exception:
                    pass

            if not clicked_signup:
                if config.DEBUG:
                    print("[DEBUG] 未能点击 Sign up 按钮，检测是否有 CF 拦截...")
                await self._manual_wait_for_cf(page, silent_first=True)
                for sel in signup_selectors:
                    try:
                        el = page.locator(sel)
                        if await el.count() > 0:
                            if config.DEBUG:
                                print(f"[DEBUG] CF 后重试点击 signup 按钮，selector={sel}")
                            await el.first.click()
                            try:
                                await page.wait_for_selector(
                                    'input[type="email"], input[name="email"], input[id*="email"], input',
                                    timeout=5000
                                )
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        pass

            print(f"[{index}] 调用 EmailService.create_email() 创建临时邮箱")
            email, mailbox = self.email_service.create_email()
            print(f"[{index}] EmailService.create_email() 返回: email={email} mailbox={mailbox}")
            if not email:
                print(f"[{index}] 无法创建临时邮箱，跳过")
                return None
            print(f"[{index}] 使用邮箱: {email}")

            print(f"[{index}] 开始在页面填入邮箱和密码")
            filled_email = await self._fill_signup(page, email, password, submit=False)
            print(f"[{index}] _fill_signup 返回: {filled_email}")
            if not filled_email:
                if config.DEBUG:
                    print(f"[{index}] 无法在页面上填入邮箱字段，尝试检测是否有 CF 阻拦...")
                await self._manual_wait_for_cf(page, silent_first=False)
                filled_email = await self._fill_signup(page, email, password, submit=False)
                if not filled_email and config.DEBUG:
                    print(f"[{index}] CF 过后仍无法填入邮箱字段")

            try:
                print(f"[{index}] 触发验证码请求 (_request_verification)")
                triggered = await self._request_verification(page)
                print(f"[{index}] _request_verification 返回: {triggered}")
                if config.DEBUG:
                    print(f"[DEBUG] 触发验证码发送: {triggered}")
            except Exception as e:
                print(f"[{index}] _request_verification 抛出异常: {e}")
                triggered = False

            got = False
            # 仅在页面进入验证码输入/提示后再开始轮询邮箱获取验证码
            if triggered:
                max_wait = getattr(config, 'VERIFICATION_INPUT_WAIT_SECONDS', 60)
                check_selectors = [
                    'input[name="code"]',
                    'input[id*="code"]',
                    'input[placeholder*="code"]',
                ]
                text_selectors = [
                    'text=Email sent',
                    'text=Verification email sent',
                    'text=Verify',
                ]
                found = False
                print(f"[{index}] 等待进入验证码输入页面（最多 {max_wait}s），每 1s 检查一次...")
                elapsed = 0
                try:
                    while elapsed < max_wait:
                        for sel in check_selectors:
                            try:
                                loc = page.locator(sel)
                                if await loc.count() > 0:
                                    found = True
                                    break
                            except Exception:
                                pass
                        if not found:
                            for sel in text_selectors:
                                try:
                                    loc = page.locator(sel)
                                    if await loc.count() > 0:
                                        found = True
                                        break
                                except Exception:
                                    pass
                        if found:
                            break
                        await asyncio.sleep(1)
                        elapsed += 1
                    if found:
                        print(f"[{index}] 检测到验证码输入页面，开始轮询验证码 (mailbox={mailbox})")
                        got = await self._fill_verification(page, mailbox)
                        print(f"[{index}] _fill_verification 返回: {got}")
                        if not got:
                            print(f"[{index}] 验证码填入/获取失败")
                    else:
                        print(f"[{index}] 超时 {max_wait}s，仍未检测到验证码输入页面，跳过轮询")
                        got = False
                except Exception as e:
                    print(f"[{index}] 等待验证码输入页面过程中发生异常: {e}")
                    got = False
            else:
                print(f"[{index}] _request_verification 未触发发送或未检测到变化，跳过验证码轮询")

            try:
                display_name = self._generate_name()
                first, last = (display_name.split(' ', 1) + [""])[:2]
                try:
                    f_sel = page.locator('input[name="givenName"]')
                    if await f_sel.count() > 0:
                        await f_sel.fill(first)
                except Exception:
                    pass
                try:
                    l_sel = page.locator('input[name="familyName"]')
                    if await l_sel.count() > 0:
                        await l_sel.fill(last)
                except Exception:
                    pass

                try:
                    p_sel = page.locator('input[name="password"]')
                    if await p_sel.count() > 0:
                        await p_sel.fill(password)
                except Exception:
                    for s in ['input[type="password"]', 'input[id*="password"]', 'input[placeholder*="password"]']:
                        try:
                            el = page.locator(s)
                            if await el.count() > 0:
                                await el.first.fill(password)
                                break
                        except Exception:
                            pass

                submitted = False
                for btn_sel in [
                    'button:has-text("Complete sign up")',
                    'button:has-text("Complete signup")',
                    'button:has-text("Complete")',
                    'button[type="submit"]',
                    'button:has-text("Next")'
                ]:
                    try:
                        btn = page.locator(btn_sel)
                        if await btn.count() > 0:
                            if config.DEBUG:
                                print(f"[DEBUG] 点击完成注册按钮 selector={btn_sel}")
                            await btn.first.click()
                            submitted = True
                            break
                    except Exception:
                        pass

                if not submitted and config.DEBUG:
                    print('[DEBUG] 未能找到合适的 Complete/Submit 按钮')
            except Exception as e:
                if config.DEBUG:
                    print(f"[DEBUG] 填写个人资料/提交时发生异常: {e}")

            await self._manual_wait_for_cf(page)

            if config.DEBUG:
                await asyncio.sleep(1)
                print(f"[DEBUG] Second CF passed. Current URL: {page.url}")
                try:
                    print(f"[DEBUG] Page title: {await page.title()}")
                except Exception:
                    print("[DEBUG] Page title not available.")

            await asyncio.sleep(5)

            try:
                display_name = self._generate_name()
                first, last = (display_name.split(' ', 1) + [""])[:2]
                if config.DEBUG:
                    print(f"[DEBUG] Attempting to fill profile after CF: first={first} last={last}")

                first_selectors = [
                    'input[name="givenName"]',
                    'input[placeholder*="First"]',
                    'input[aria-label*="First"]',
                    'input[id*="first"]',
                ]
                last_selectors = [
                    'input[name="familyName"]',
                    'input[placeholder*="Last"]',
                    'input[aria-label*="Last"]',
                    'input[id*="last"]',
                ]
                pwd_selectors = [
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[id*="password"]',
                    'input[placeholder*="Password"]',
                ]

                filled_any = False
                for s in first_selectors:
                    try:
                        el = page.locator(s)
                        if await el.count() > 0:
                            await el.first.fill(first)
                            filled_any = True
                            if config.DEBUG:
                                print(f"[DEBUG] Filled first name using selector: {s}")
                            break
                    except Exception:
                        pass

                for s in last_selectors:
                    try:
                        el = page.locator(s)
                        if await el.count() > 0:
                            await el.first.fill(last)
                            filled_any = True
                            if config.DEBUG:
                                print(f"[DEBUG] Filled last name using selector: {s}")
                            break
                    except Exception:
                        pass

                for s in pwd_selectors:
                    try:
                        el = page.locator(s)
                        if await el.count() > 0:
                            await el.first.fill(password)
                            filled_any = True
                            if config.DEBUG:
                                print(f"[DEBUG] Filled password using selector: {s}")
                            break
                    except Exception:
                        pass

                submitted2 = False
                for btn_sel in [
                    'button:has-text("Complete sign up")',
                    'button:has-text("Complete your sign up")',
                    'button:has-text("Complete signup")',
                    'button:has-text("Complete")',
                    'button[type="submit"]',
                ]:
                    try:
                        btn = page.locator(btn_sel)
                        if await btn.count() > 0:
                            try:
                                txt = (await btn.first.inner_text()).strip().lower()
                            except Exception:
                                txt = ''
                            if 'go back' in txt or 'back' == txt:
                                if config.DEBUG:
                                    print(f"[DEBUG] 跳过按钮（可能是后退）: {btn_sel} text={txt}")
                                continue
                            if config.DEBUG:
                                print(f"[DEBUG] 点击完成注册按钮 (2nd try) selector={btn_sel} text={txt}")
                            await btn.first.click()
                            submitted2 = True
                            break
                    except Exception:
                        pass

                if not submitted2 and config.DEBUG:
                    print('[DEBUG] 2nd try: 未能找到合适的 Complete/Submit 按钮')
            except Exception as e:
                if config.DEBUG:
                    print(f"[DEBUG] 在 CF 后填写资料时发生异常: {e}")

            try:
                await page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                await asyncio.sleep(2)

            # 不在此处立即抓取 token；在完成 TOS/CF 流程并进入 /account 页面后再抓取（更可靠）

            try:
                await page.wait_for_url('**/accept-tos**', timeout=30000)
                if config.DEBUG:
                    print(f"[DEBUG] 已跳转到 TOS 页面，URL: {page.url}")
            except Exception:
                if config.DEBUG:
                    print(f"[DEBUG] 等待 /accept-tos URL 超时，当前 URL: {page.url}")

            current_url = page.url
            if 'accept-tos' in current_url or 'terms' in current_url:
                try:
                    await page.wait_for_selector('button[role="checkbox"]', timeout=10000)
                except Exception:
                    if config.DEBUG:
                        print(f"[DEBUG] TOS checkbox 等待超时，URL: {page.url}，继续尝试")

                try:
                    checkboxes = page.locator('button[role="checkbox"]')
                    count = await checkboxes.count()
                    if config.DEBUG:
                        print(f"[DEBUG] 找到 {count} 个 TOS checkbox 按钮")
                    for i in range(count):
                        try:
                            cb = checkboxes.nth(i)
                            state = await cb.get_attribute('data-state')
                            if state != 'checked':
                                await cb.click()
                                await asyncio.sleep(0.4)
                                if config.DEBUG:
                                    print(f"[DEBUG] 点击了第 {i+1} 个 TOS checkbox")
                        except Exception:
                            pass
                except Exception as e:
                    if config.DEBUG:
                        print(f"[DEBUG] 点击 TOS checkbox 异常: {e}")

                try:
                    for btn_sel in [
                        'button[type="submit"]:has-text("Continue")',
                        'button:has-text("Continue")',
                    ]:
                        btn = page.locator(btn_sel)
                        if await btn.count() > 0:
                            try:
                                txt = (await btn.first.inner_text()).strip()
                            except Exception:
                                txt = ''
                            if config.DEBUG:
                                print(f"[DEBUG] 点击 TOS 提交按钮 selector={btn_sel} text={txt}")
                            await btn.first.click()
                            await asyncio.sleep(1)
                            break
                except Exception as e:
                    if config.DEBUG:
                        print(f"[DEBUG] 点击 TOS Continue 按钮异常: {e}")
            else:
                if config.DEBUG:
                    print(f"[DEBUG] 当前页面不是 TOS 页面（URL: {current_url}），跳过 TOS 点击")
            # 在完成 TOS/CF 后，等待或导航到 /account 页面再抓取 token
            try:
                await page.wait_for_url('**/account**', timeout=15000)
                if config.DEBUG:
                    print(f"[DEBUG] 已跳转到 account 页面，URL: {page.url}")
            except Exception:
                if config.DEBUG:
                    print(f"[DEBUG] 等待 /account URL 超时，尝试显式导航到 /account...")
                try:
                    await page.goto('https://accounts.x.ai/account', wait_until='networkidle', timeout=15000)
                except Exception:
                    pass

            token = {"sso": "", "sso-rw": "", "jwt": ""}
            try:
                token = await self._extract_token(context, page, listen_timeout=15)
                if not (token.get('sso') or token.get('jwt')):
                    await asyncio.sleep(2)
                    token2 = await self._extract_token(context, page, listen_timeout=10)
                    for k, v in token2.items():
                        if v and not token.get(k):
                            token[k] = v
            except Exception:
                pass

            token_struct = token if isinstance(token, dict) else {"sso": token or "", "sso-rw": "", "jwt": ""}
            any_token = token_struct.get('sso') or token_struct.get('jwt')
            success = bool(any_token)
            if any_token:
                # 将结果追加写入由 run() 创建的共享 CSV 文件（实时 flush + fsync 保证已完成条目在崩溃时仍然持久化）
                try:
                    csv_filename = getattr(self, '_csv_filename', None)
                    if not csv_filename:
                        # 兼容性回退（若 run() 未提前创建），按单任务文件写入
                        out_file = os.path.join(self.output_dir, f"key-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-1.csv")
                        with open(out_file, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(['signup_url', 'email', 'password', 'sso token'])
                            writer.writerow([config.SIGNUP_URL, email, password, any_token])
                        print(f"[{index}] 成功注册并保存到: {out_file}")
                    else:
                        # 异步地在共享文件上加锁写入并立即刷新到磁盘
                        lock = getattr(self, '_csv_lock', None)
                        if lock is None:
                            # 如果没有 lock，则同步写入（极端回退）
                            self._csv_writer.writerow([config.SIGNUP_URL, email, password, any_token])
                            try:
                                self._csv_file.flush()
                                os.fsync(self._csv_file.fileno())
                            except Exception:
                                pass
                        else:
                            try:
                                async with lock:
                                    self._csv_writer.writerow([config.SIGNUP_URL, email, password, any_token])
                                    try:
                                        self._csv_file.flush()
                                        os.fsync(self._csv_file.fileno())
                                    except Exception:
                                        pass
                            except Exception as e:
                                # 写入锁或写入过程出错，记录并回退到单文件写入
                                if config.DEBUG:
                                    print(f"[{index}] 共享 CSV 写入出错，回退单文件写入: {e}")
                                out_file = os.path.join(self.output_dir, f"key-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-1.csv")
                                with open(out_file, 'w', newline='', encoding='utf-8') as f:
                                    writer = csv.writer(f)
                                    writer.writerow(['signup_url', 'email', 'password', 'sso token'])
                                    writer.writerow([config.SIGNUP_URL, email, password, any_token])
                                print(f"[{index}] 成功注册并保存到: {out_file}")
                        if getattr(self, '_csv_filename', None):
                            print(f"[{index}] 成功注册并追加到: {self._csv_filename}")
                except Exception as e:
                    print(f"[{index}] 写入 CSV 发生异常: {e}")
                # 成功后立即进行最小清理并返回，跳过后续的 TOS 接受和多余步骤。
                deleted = False
                try:
                    # 尝试删除临时邮箱（不影响主流程）
                    try:
                        self.email_service.delete_mailbox(email)
                        deleted = True
                    except Exception as e:
                        if config.DEBUG:
                            print(f"[{index}] 删除临时邮箱时发生异常: {e}")
                        deleted = False
                except Exception as e:
                    if config.DEBUG:
                        print(f"[{index}] 删除临时邮箱外层异常: {e}")
                    deleted = False

                if deleted:
                    print(f"[{index}] 已成功删除临时邮箱: {email}")
                else:
                    print(f"[{index}] 未能删除临时邮箱（可忽略）: {email}")

                # 返回 token，finally 块会负责关闭/释放浏览器资源并继续下一个任务
                return token
            else:
                print(f"[{index}] 未能获取 sso token，注册可能未完成")

            try:
                sso_val = token_struct.get('sso')
                sso_rw_val = token_struct.get('sso-rw')
                if UserAgreementService is not None and sso_val and sso_rw_val:
                    uas = UserAgreementService()
                    resp = uas.accept_tos_version(sso_val, sso_rw_val, impersonate="chrome120", user_agent=None, cf_clearance=None, proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None)
                    if config.DEBUG:
                        print(f"[grok_reg] accept_tos_version response: {resp}")
            except Exception:
                pass

            try:
                self.email_service.delete_mailbox(email)
            except Exception:
                pass

            try:
                if config.DEBUG and not success:
                    try:
                        debug_dir = os.path.join(self.output_dir, "debug")
                        os.makedirs(debug_dir, exist_ok=True)
                        ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
                        try:
                            img_path = os.path.join(debug_dir, f"fail-{ts}-{index}.png")
                            await page.screenshot(path=img_path, full_page=True)
                            print(f"[DEBUG] 保存失败时的页面截图: {img_path}")
                        except Exception as e:
                            print(f"[DEBUG] 无法保存截图: {e}")
                        try:
                            html_path = os.path.join(debug_dir, f"fail-{ts}-{index}.html")
                            html = await page.content()
                            with open(html_path, 'w', encoding='utf-8') as fh:
                                fh.write(html)
                            print(f"[DEBUG] 保存失败时的页面 HTML: {html_path}")
                        except Exception as e:
                            print(f"[DEBUG] 无法保存页面 HTML: {e}")
                        try:
                            print(f"[DEBUG] 未获取 token，暂停 15s 以便人工查看浏览器...")
                            await asyncio.sleep(15)
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                await context.close()
            except Exception:
                pass

        finally:
            if got_browser_from_pool and solver is not None:
                try:
                    await solver.browser_pool.put((index_bp, browser, browser_config))
                except Exception:
                    if config.KEEP_BROWSER_OPEN and not locals().get('success', False):
                        print(f"[DEBUG] KEEP_BROWSER_OPEN enabled, 未关闭浏览器 (index={index})")
                    else:
                        try:
                            await browser.close()
                        except Exception:
                            pass
            else:
                if cam_owner is not None:
                    try:
                        if config.KEEP_BROWSER_OPEN and not locals().get('success', False):
                            print(f"[DEBUG] KEEP_BROWSER_OPEN enabled, 跳过 cam_owner.__aexit__ (index={index})")
                        else:
                            await cam_owner.__aexit__(None, None, None)
                    except Exception:
                        pass
                else:
                    try:
                        if config.KEEP_BROWSER_OPEN and not locals().get('success', False):
                            print(f"[DEBUG] KEEP_BROWSER_OPEN enabled, 未关闭浏览器 (index={index})")
                        else:
                            await browser.close()
                    except Exception:
                        pass

        return token

    async def run(self):
        # 支持总任务数（TOTAL_TASKS），并使用 Semaphore 控制并发数量（threads）
        if ExternalTurnstileServer is not None:
            await self._init_external_solver()

        total_tasks = getattr(config, 'TOTAL_TASKS', self.threads) or self.threads
        concurrency = self.threads

        # 为所有任务创建一个共享的 CSV 输出（文件名包含总任务数），以便实时追加并能在异常退出时保留已完成条目
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        csv_filename = os.path.join(self.output_dir, f"key-{timestamp}-{total_tasks}.csv")
        # 存储在实例上，register_task 会使用 _csv_lock/_csv_writer/_csv_file
        self._csv_filename = csv_filename
        self._csv_lock = asyncio.Lock()
        # 打开文件为 append 模式，若文件为空则写入 header
        try:
            # 确保目录存在（run() 之前已创建，但再确保一次）
            os.makedirs(self.output_dir, exist_ok=True)
            new_file = not os.path.exists(csv_filename)
            self._csv_file = open(csv_filename, 'a', newline='', encoding='utf-8')
            self._csv_writer = csv.writer(self._csv_file)
            if new_file:
                # 写入表头
                try:
                    self._csv_writer.writerow(['signup_url', 'email', 'password', 'sso token'])
                    self._csv_file.flush()
                    try:
                        os.fsync(self._csv_file.fileno())
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception as e:
            if config.DEBUG:
                print(f"[grok_reg] 无法创建共享 CSV 文件 {csv_filename}: {e}")
            # 将这些属性删除以回退到每任务单文件写入
            self._csv_filename = None
            try:
                if hasattr(self, '_csv_file') and not self._csv_file.closed:
                    self._csv_file.close()
            except Exception:
                pass

        # 初始化中央 Cloudflare 提示器的数据结构与后台任务
        self._cf_queue = asyncio.Queue()
        self._cf_pending = {}
        # 后台任务：统一向控制台提示需要手动通过 CF 的浏览器实例，避免多个任务同时阻塞 stdin
        try:
            asyncio.create_task(self._cf_prompt_handler())
        except Exception:
            # 在某些同步启动路径上可能没有运行时 loop，run 时会再次启动
            pass

        semaphore = asyncio.Semaphore(concurrency)

        async def _worker(idx: int):
            await semaphore.acquire()
            try:
                return await self.register_task(idx)
            finally:
                try:
                    semaphore.release()
                except Exception:
                    pass

        wrappers = [_worker(i + 1) for i in range(total_tasks)]
        try:
            results = await asyncio.gather(*wrappers, return_exceptions=True)
        finally:
            if self.external_solver is not None:
                solver = self.external_solver
                try:
                    while not solver.browser_pool.empty():
                        try:
                            item = solver.browser_pool.get_nowait()
                        except Exception:
                            break
                        try:
                            _, br, _ = item
                            if br:
                                try:
                                    await br.close()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
                # 关闭共享 CSV 文件句柄（若打开）
                try:
                    csvf = getattr(self, '_csv_file', None)
                    if csvf:
                        try:
                            csvf.flush()
                        except Exception:
                            pass
                        try:
                            csvf.close()
                        except Exception:
                            pass
                except Exception:
                    pass
        return results


def main(threads: int = None):
    reg = Registrar(threads=threads)

    import sys
    import warnings

    if sys.platform == "win32":
        warnings.filterwarnings("ignore", category=ResourceWarning)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(reg.run())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    for t in pending:
                        t.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                loop.run_until_complete(loop.shutdown_default_executor())
            except Exception:
                pass
            loop.close()
        warnings.resetwarnings()
        return result
    else:
        return asyncio.run(reg.run())

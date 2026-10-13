#!/usr/bin/env python3
"""把微信参谋页面做成吸附在微信窗口旁边的悬浮面板（macOS）。
- 用 Quartz 窗口列表每 0.25s 读微信主窗口的位置/大小，面板贴在它右侧（右边放不下就贴左侧），高度跟随
- 微信或面板在前台时显示，否则隐藏；微信窗口最小化/关闭时隐藏
- 不需要辅助功能权限；内容是 live.py 提供的 http://127.0.0.1:8765
用法: ../.venv/bin/python dock.py [--url http://127.0.0.1:8765] [--width 380] [--gap 8] [--always]
"""
import argparse, os, sys, json, urllib.request
import objc
from AppKit import (NSApplication, NSPanel, NSButton, NSFont, NSBezelStyleInline, NSColor, NSScreen, NSWorkspace, NSMakeRect, NSObject, NSTimer, NSRunningApplication,
                    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable, NSWindowStyleMaskNonactivatingPanel,
                    NSWindowStyleMaskUtilityWindow, NSFloatingWindowLevel, NSBackingStoreBuffered, NSApplicationActivationPolicyAccessory,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary)
from Foundation import NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration
import Quartz

WECHAT_BUNDLE = 'com.tencent.xinWeChat'

def wechat_pids():
    return {a.processIdentifier() for a in NSRunningApplication.runningApplicationsWithBundleIdentifier_(WECHAT_BUNDLE)}

def wechat_main_window(pids):
    """返回微信最大的普通窗口 (x, y, w, h)，CG 坐标（左上原点）；没有则 None。"""
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID) or []:
        if w.get('kCGWindowOwnerPID') not in pids or w.get('kCGWindowLayer', 0) != 0 or (w.get('kCGWindowAlpha', 1) or 0) < 0.5: continue
        b = w.get('kCGWindowBounds') or {}
        x, y, ww, hh = float(b.get('X', 0)), float(b.get('Y', 0)), float(b.get('Width', 0)), float(b.get('Height', 0))
        if ww < 300 or hh < 300: continue           # 跳过悬浮小窗 / 通知
        if best is None or ww * hh > best[2] * best[3]: best = (x, y, ww, hh)
    return best

class Dock(NSObject):
    def initWithArgs_(self, a):
        self = objc.super(Dock, self).init()
        self.a = a; self.last = None; self.my_pid = os.getpid()
        mask = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable | NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(100, 100, a.width, 600), mask, NSBackingStoreBuffered, False)
        self.panel.setTitle_('微信参谋'); self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False); self.panel.setFloatingPanel_(True); self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.panel.setMinSize_((260, 300))
        cfg = WKWebViewConfiguration.alloc().init()
        self.web = WKWebView.alloc().initWithFrame_configuration_(self.panel.contentView().bounds(), cfg)
        self.web.setAutoresizingMask_(18)  # width + height sizable
        self.panel.contentView().addSubview_(self.web)
        # 折叠/展开按钮：右上角，折叠后面板缩成窄条
        self.collapsed = False; self.saved_width = a.width
        self.btn = NSButton.alloc().initWithFrame_(NSMakeRect(a.width - 34, self.panel.contentView().bounds().size.height - 30, 28, 24))
        self.btn.setTitle_('◀'); self.btn.setBezelStyle_(NSBezelStyleInline); self.btn.setFont_(NSFont.systemFontOfSize_(11))
        self.btn.setAutoresizingMask_(1 | 4)   # 贴右(MinXMargin) + 贴顶(MinYMargin)
        self.btn.setTarget_(self); self.btn.setAction_('toggle:'); self.btn.setToolTip_('折叠 / 展开')
        self.panel.contentView().addSubview_(self.btn)
        self.web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(a.url.rstrip('/') + '/?embed=1')))
        self.idle_since = 0; self.timer = None; self.arm_(a.fast)
        # 折叠时的新建议提示：每 2s 读 state.json，updated 变了且处于折叠 → 按钮变红点
        self.seen_updated = None; self.has_new = False; self.blink = False
        self.poll_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(2.0, self, 'poll:', None, True)
        self.blink_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.6, self, 'blinkTick:', None, True)
        return self

    COLLAPSED_W = 36

    def poll_(self, _):
        try:
            st = json.load(urllib.request.urlopen(self.a.url.rstrip('/') + '/state.json', timeout=1.5))
        except Exception:
            return
        upd = st.get('updated')
        if self.seen_updated is None:
            self.seen_updated = upd; return
        if upd != self.seen_updated:
            self.seen_updated = upd
            if self.collapsed:
                self.has_new = True
                self.btn.setToolTip_('有新建议，点击展开')

    def blinkTick_(self, _):
        if not (self.collapsed and self.has_new): return
        self.blink = not self.blink
        self.btn.setTitle_('🔴' if self.blink else '●')

    def _clear_new(self):
        self.has_new = False; self.btn.setToolTip_('折叠 / 展开')

    def toggle_(self, _):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.saved_width = self.panel.frame().size.width
            self.web.setHidden_(True); self.btn.setTitle_('▶')
            self.seen_updated = self.seen_updated   # 折叠时从当前状态起算
            self.panel.setMinSize_((self.COLLAPSED_W, 300)); self.panel.setMaxSize_((self.COLLAPSED_W, 10000))
        else:
            self.panel.setMaxSize_((10000, 10000)); self.panel.setMinSize_((260, 300))
            self.web.setHidden_(False); self.btn.setTitle_('◀'); self.web.reload(); self._clear_new()
        self.last = None   # 让 tick 立刻按新宽度重排

    def arm_(self, interval):
        if self.timer: self.timer.invalidate()
        self.cur = interval
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(interval, self, 'tick:', None, True)

    def tick_(self, _):
        pids = wechat_pids()
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        front_pid = front.processIdentifier() if front else -1
        win = wechat_main_window(pids) if pids else None
        visible_ok = self.a.always or front_pid in pids or front_pid == self.my_pid or self.panel.isKeyWindow()
        if not win or not visible_ok:
            if self.panel.isVisible(): self.panel.orderOut_(None)
            if self.cur != self.a.slow: self.arm_(self.a.slow)
            return
        x, y, w, h = win
        width = self.COLLAPSED_W if self.collapsed else (self.panel.frame().size.width if not self.collapsed and self.panel.frame().size.width > self.COLLAPSED_W else self.saved_width)
        gap = self.a.gap
        # CG(左上原点) → Cocoa(主屏左下原点)
        main_h = NSScreen.screens()[0].frame().size.height
        # 找包含微信窗口中心的屏幕，决定左右是否放得下
        cx, cy_cocoa = x + w / 2, main_h - (y + h / 2)
        scr = next((s for s in NSScreen.screens() if s.frame().origin.x <= cx <= s.frame().origin.x + s.frame().size.width and s.frame().origin.y <= cy_cocoa <= s.frame().origin.y + s.frame().size.height), NSScreen.screens()[0])
        vf = scr.visibleFrame(); sx0, sx1 = vf.origin.x, vf.origin.x + vf.size.width
        px = x + w + gap
        if px + width > sx1:                       # 右边放不下 → 贴左侧
            px = x - gap - width
            if px < sx0: px = max(sx0, sx1 - width) # 左边也放不下 → 叠在屏幕右缘
        py = main_h - (y + h)                      # 底边对齐
        target = (round(px), round(py), round(width), round(h))
        import time
        if target != self.last:
            self.panel.setFrame_display_(NSMakeRect(*target), True); self.last = target; self.idle_since = time.time()
            if self.cur != self.a.fast: self.arm_(self.a.fast)          # 在动：快采样
        elif self.cur == self.a.fast and time.time() - self.idle_since > 2 and front_pid not in pids:
            self.arm_(self.a.slow)                                        # 静止且微信不在前台：慢采样
        if not self.panel.isVisible(): self.panel.orderFront_(None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8765')
    ap.add_argument('--width', type=float, default=380)
    ap.add_argument('--gap', type=float, default=8)
    ap.add_argument('--always', action='store_true', help='微信不在前台时也保持显示')
    ap.add_argument('--fast', type=float, default=0.25, help='窗口在动或微信在前台时的采样间隔(秒)')
    ap.add_argument('--slow', type=float, default=1.0, help='静止且微信不在前台时的采样间隔(秒)')
    a = ap.parse_args()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # 不占 Dock
    global _dock
    _dock = Dock.alloc().initWithArgs_(a)   # 保活引用
    print(f'[dock] 跟随微信窗口，宽 {a.width:.0f}，{a.url}；Ctrl-C 退出', flush=True)
    app.run()

if __name__ == '__main__':
    main()

"""Opt-in native Stop drag QA. Never part of default test discovery.

Run with the project Python 3.12 after building current UI assets:
  experiments/desktop-shell/.venv/bin/python scripts/smoke_stop.py

Outputs only artifacts/stop-smoke by default. Uses QtTest pointer/key/wheel
events against the actual QtWebEngine widget; JS only reads state/geometry
and installs passive evidence listeners. No application state is assigned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from optics_ui import desktop


SNAPSHOT = r"""(() => {
  const root=document.getElementById('optics-review');
  const state=root?.__opticsState;
  const section=document.getElementById('o-section');
  const handle=document.getElementById('o-stop-handle');
  const plane=section?.querySelector('[data-stop-plane]');
  const aperture=plane?.querySelector('path[stroke-dasharray]');
  const rect=element=>{const r=element?.getBoundingClientRect();return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};
  const visible=element=>!!element&&element.getClientRects().length>0&&getComputedStyle(element).display!=='none'&&getComputedStyle(element).visibility!=='hidden';
  const index=state?.stop?.surface_index??state?.lenses?.length*2;
  const boundCsd=state?.lenses?.[Math.floor((index-1)/2)]?.surfaces?.[(index-1)%2]?.aperture;
  const outerZ=state?state.source+state.lenses.reduce((sum,l)=>sum+l.thickness,0)+state.gaps.gap12+state.gaps.gap23:null;
  let independentScale=null;
  if(aperture&&visible(section)){
    const box=aperture.getBBox(),matrix=aperture.getScreenCTM();
    independentScale=box.height*Math.hypot(matrix.c,matrix.d)/(2*boundCsd);
  }
  return {section:state?.section,stop:state?.stop,source:state?.source,
    lens_parameters:state?{lenses:state.lenses,source:state.source,gaps:state.gaps}:null,
    csd:boundCsd,expected_outer_z:outerZ,expected_outer_index:state?.lenses?.length*2,
    plane_z:plane?Number(plane.dataset.zMm):null,reported_pixels_per_mm:Number(section?.dataset.pixelsPerMm)||null,
    independent_pixels_per_mm:independentScale,handle:rect(handle),toggle:rect(document.getElementById('o-view-toggle')),
    section_rect:rect(section),handle_visible:visible(handle),plane_visible:visible(section)&&!!plane,
    focused_id:document.activeElement?.id||null,viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},
    handle_label:handle?.textContent||null};
})()"""


class StopPointerRunner(QObject):
    def __init__(self, app, window, page, bridge, stats, output_dir, smoke_config):
        super().__init__(app)
        self.app,self.window,self.page,self.bridge,self.stats=app,window,page,bridge,stats
        self.output=output_dir
        self.output.mkdir(parents=True,exist_ok=True)
        # v1 centralWidget is the native activity bar/page container. Pointer
        # coordinates belong to the embedded WebEngine viewport, not its host.
        content=window.centralWidget()
        chrome_width=max(0,window.width()-content.width())
        chrome_height=max(0,window.height()-content.height())
        content.setFixedSize(1440,900)
        self.view=getattr(window, 'renderer', window.centralWidget())
        self.window.resize(1440+chrome_width,900+chrome_height)
        self.exit_code=1
        self.started=time.monotonic()
        self.checks=[]
        self.result={"kind":"actual-QtTest-stop-pointer-QA","python":sys.version,"platform":platform.platform(),
                     "input_method":"QtTest QWidget mouse/key events and QWindow wheel events",
                     "js_state_mutation":False,"backend_jobs_executed":False,"checks":self.checks,"actions":[],"states":{}}
        QTimer.singleShot(100,self.wait_ready)

    def evaluate(self,expression):
        loop=QEventLoop()
        values=[]
        watchdog=QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(4000)
        def completed(raw):
            values.append(raw)
            loop.quit()
        self.page.runJavaScript("JSON.stringify("+expression+")",completed)
        loop.exec()
        watchdog.stop()
        if not values or not values[0]:
            raise RuntimeError("DOM observation did not return JSON")
        return json.loads(values[0])

    def wait_ready(self):
        try:
            ready=self.evaluate("document.readyState==='complete' && !!document.getElementById('optics-review')?.__opticsState && typeof document.getElementById('o-stop-handle')?.onpointerdown==='function'")
            if ready:
                QTimer.singleShot(150,self.run_checks)
            elif time.monotonic()-self.started<25:
                QTimer.singleShot(100,self.wait_ready)
            else:
                raise RuntimeError("Current built UI does not expose the Stop drag controls")
        except Exception as error:
            self.fail(error)

    def check(self,name,passed,details=None):
        self.checks.append({"name":name,"pass":bool(passed),"details":details or {}})
        if not passed:
            raise AssertionError(name)

    def snapshot(self,name):
        state=self.evaluate(SNAPSHOT)
        state["lens_fingerprint"]=hashlib.sha256(json.dumps(state["lens_parameters"],sort_keys=True).encode()).hexdigest()
        self.result["states"][name]=state
        return state

    def point(self,css_x,css_y,state):
        factor_x=self.view.width()/state["viewport"]["width"]
        factor_y=self.view.height()/state["viewport"]["height"]
        logical=QPoint(round(css_x*factor_x),round(css_y*factor_y))
        dpr=self.view.devicePixelRatioF()
        return logical,{"css":[css_x,css_y],"qt_logical":[logical.x(),logical.y()],
                        "physical_device_pixels":[logical.x()*dpr,logical.y()*dpr],"dpr":dpr}

    def target_point(self,view_point):
        target=self.view.focusProxy() or self.view
        return target,target.mapFromGlobal(self.view.mapToGlobal(view_point))

    def click_rect(self,rect,state,action):
        point,coordinates=self.point(rect["x"]+rect["width"]/2,rect["y"]+rect["height"]/2,state)
        target,local=self.target_point(point)
        self.result["actions"].append({"action":action,"coordinates":coordinates,"target":target.metaObject().className()})
        QTest.mouseClick(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,local,20)
        QTest.qWait(180)

    def drag(self,before,label):
        handle=before["handle"]
        css_x,css_y=handle["x"]+handle["width"]/2,handle["y"]+handle["height"]/2
        start,start_record=self.point(css_x,css_y,before)
        end,end_record=self.point(css_x+40,css_y,before)
        target,local_start=self.target_point(start)
        _,local_end=self.target_point(end)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.mouseMove(target,local_start,10)
        QTest.mousePress(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,local_start,20)
        QTest.qWait(30)
        for i in range(1,11):
            point=QPoint(round(local_start.x()+(local_end.x()-local_start.x())*i/10),local_start.y())
            QTest.mouseMove(target,point,10)
            QTest.qWait(15)
        QTest.mouseRelease(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,local_end,20)
        QTest.qWait(180)
        after=self.snapshot(label)
        actual_css_delta=(end.x()-start.x())*before["viewport"]["width"]/self.view.width()
        scale=before["independent_pixels_per_mm"]
        expected=actual_css_delta/scale
        observed=after["plane_z"]-before["plane_z"]
        tolerance=1.1/scale+1e-6
        self.result["actions"].append({"action":label,"start":start_record,"end":end_record,"target":target.metaObject().className(),
                                       "expected_delta_mm":expected,"observed_delta_mm":observed,"tolerance_mm":tolerance})
        self.check(label+"_moves_stop",after["stop"]["position_mode"]=="absolute" and observed>0,{"before_z":before["plane_z"],"after_z":after["plane_z"]})
        self.check(label+"_pixel_mapping",abs(observed-expected)<=tolerance,{"expected_mm":expected,"observed_mm":observed,"tolerance_mm":tolerance})
        self.check(label+"_preserves_all_lens_parameters",after["lens_fingerprint"]==before["lens_fingerprint"])
        return after

    def run_checks(self):
        try:
            self.evaluate("(()=>{window.__STOP_QA_EVENTS__=[];for(const type of ['pointerdown','pointermove','pointerup','keydown','wheel'])document.addEventListener(type,e=>{if(window.__STOP_QA_EVENTS__.length<100)window.__STOP_QA_EVENTS__.push({type:e.type,trusted:e.isTrusted,target:e.target.id||null,x:e.clientX??null,key:e.key??null});},true);return true;})()")
            initial=self.snapshot("initial_3d")
            self.click_rect(initial["toggle"],initial,"open_2d_via_QTest_click")
            before=self.snapshot("before_drag")
            self.check("2d_click_shows_stop_handle_and_plane",before["section"] and before["handle_visible"] and before["plane_visible"])
            self.check("default_stop_at_farthest_outer_face",before["stop"]["position_mode"]=="surface" and before["stop"]["surface_index"]==before["expected_outer_index"] and abs(before["plane_z"]-before["expected_outer_z"])<1e-9)
            self.check("display_mapping_matches_svg_geometry",abs(before["reported_pixels_per_mm"]-before["independent_pixels_per_mm"])<1e-6,
                       {"reported":before["reported_pixels_per_mm"],"independent":before["independent_pixels_per_mm"],"csd":before["csd"]})
            first=self.drag(before,"drag_40px")
            section=first["section_rect"]
            point,coordinates=self.point(section["x"]+section["width"]*.65,section["y"]+section["height"]*.6,first)
            window_point=self.window.mapFromGlobal(self.view.mapToGlobal(point))
            QTest.wheelEvent(self.window.windowHandle(),QPointF(window_point),QPoint(0,120))
            QTest.qWait(200)
            zoomed=self.snapshot("zoomed")
            self.result["actions"].append({"action":"native_QTest_wheel_zoom","coordinates":coordinates,"angle_delta":[0,120]})
            self.check("wheel_changes_pixels_per_mm",abs(zoomed["independent_pixels_per_mm"]-first["independent_pixels_per_mm"])>1e-6)
            second=self.drag(zoomed,"zoomed_drag_40px")
            self.check("zoom_adjusts_same_pixel_displacement",abs((second["plane_z"]-zoomed["plane_z"])-(first["plane_z"]-before["plane_z"]))>1e-4)
            target=self.view.focusProxy() or self.view
            focused=second
            for _ in range(50):
                if focused["focused_id"]=="o-stop-handle":break
                QTest.keyClick(target,Qt.Key.Key_Tab)
                QTest.qWait(25)
                focused=self.evaluate(SNAPSHOT)
            self.check("stop_handle_keyboard_focus",focused["focused_id"]=="o-stop-handle")
            QTest.keyClick(target,Qt.Key.Key_Right)
            QTest.qWait(150)
            keyboard=self.snapshot("after_arrow_right")
            self.check("arrow_right_moves_point_one_mm",abs(keyboard["plane_z"]-second["plane_z"]-.1)<1e-8)
            self.check("keyboard_preserves_all_lens_parameters",keyboard["lens_fingerprint"]==before["lens_fingerprint"])
            self.click_rect(keyboard["toggle"],keyboard,"return_3d_via_QTest_click")
            hidden=self.snapshot("back_in_3d")
            self.check("3d_hides_stop_handle_and_2d_plane",not hidden["section"] and not hidden["handle_visible"] and not hidden["plane_visible"])
            self.click_rect(hidden["toggle"],hidden,"restore_2d_via_QTest_click")
            restored=self.snapshot("restored_2d")
            self.check("2d_restore_preserves_stop_position",restored["handle_visible"] and abs(restored["plane_z"]-keyboard["plane_z"])<1e-9)
            events=self.evaluate("window.__STOP_QA_EVENTS__")
            self.result["browser_input_events"]=events
            for kind in ("pointerdown","pointermove","pointerup","wheel","keydown"):
                self.check(kind+"_trusted_browser_event",any(e["type"]==kind and e["trusted"] for e in events))
            self.check("no_javascript_errors",self.stats["javascript_errors"]==0)
            self.finish()
        except Exception as error:
            self.fail(error)

    def fail(self,error):
        self.result["error"]={"type":type(error).__name__,"message":str(error)}
        try:self.result["browser_input_events"]=self.evaluate("window.__STOP_QA_EVENTS__||[]")
        except Exception:pass
        self.finish()

    def finish(self):
        self.result["seconds"]=time.monotonic()-self.started
        self.result["resource_policy"]=dict(self.stats)
        self.result["actual_content_size"]=[self.view.width(),self.view.height()]
        self.result["screenshot_saved"]=self.view.grab().save(str(self.output/"stop-2d.png"))
        self.result["passed"]=bool(self.checks) and all(c["pass"] for c in self.checks) and "error" not in self.result
        self.exit_code=0 if self.result["passed"] else 1
        (self.output/"results.json").write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Stop pointer smoke:","PASS" if self.exit_code==0 else "FAIL",str(self.output/"results.json"),flush=True)
        self.window.close_for_shutdown()
        QTimer.singleShot(0,self.app.quit)


def main():
    parser=argparse.ArgumentParser(description="Opt-in native Qt Stop drag QA")
    parser.add_argument("--output-dir",type=Path,default=ROOT/"artifacts/stop-smoke")
    args=parser.parse_args()
    # Test-only runner substitution; production host files and UI files are unchanged.
    desktop.SmokeRunner=StopPointerRunner
    return desktop.main(["--smoke","--output-dir",str(args.output_dir.resolve())])


if __name__=="__main__":
    raise SystemExit(main())

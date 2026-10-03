"""Opt-in actual Qt Chief/default-Stop GUI QA; not default test discovery."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QPoint,Qt,QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from optics_ui import desktop
from scripts.smoke_stop import StopPointerRunner


SNAPSHOT=r"""(()=>{
  const root=document.getElementById('optics-review'),state=root.__opticsState,preview=root.__rayPreview||{};
  const section=document.getElementById('o-section'),plane=section.querySelector('[data-stop-plane]');
  const rect=e=>{const r=e?.getBoundingClientRect();return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};
  const visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden';
  const paths=[...section.querySelectorAll('[data-ray-kind]')],grouped={};
  for(const path of paths)(grouped[path.dataset.rayKind]??=[]).push([path.dataset.rayStatus,path.getAttribute('d')]);
  const rays=(preview.rays||[]).map(r=>({kind:r.kind,status:r.status,point_count:(r.points||[]).length,
    finite:(r.points||[]).every(p=>Number.isFinite(p.z)&&Number.isFinite(p.y)),
    on_axis:(r.points||[]).every(p=>Math.abs(p.y)<1e-9),end_z:r.points?.at(-1)?.z??null,image_height_mm:r.image_height_mm??null,
    passes_stop_center:(r.points||[]).some(p=>Math.abs(p.z-(preview.stop?.z_mm??NaN))<1e-8&&Math.abs(p.y)<1e-9)}));
  return {section:state.section,stop:state.stop,plane_z:plane?Number(plane.dataset.zMm):null,preview_stop:preview.stop||null,
    source:state.source,thickness:state.lenses[0].thickness,
    expected_rear_z:state.source+state.lenses.reduce((sum,l)=>sum+l.thickness,0)+state.gaps.gap12+state.gaps.gap23,
    expected_rear_csd:state.lenses.at(-1).surfaces[1].aperture,scale:Number(section.dataset.pixelsPerMm),
    rays:rays,preview_status:preview.status||null,image_z_mm:preview.image_z_mm??null,
    ray_counts:Object.fromEntries(Object.entries(grouped).map(([kind,list])=>[kind,list.length])),
    paths_finite:paths.every(path=>!/NaN|Infinity/.test(path.getAttribute('d')||'')),
    overlay_visible:visible(section)&&paths.length>0,tools_visible:visible(document.getElementById('o-ray-tools')),
    toggle:rect(document.getElementById('o-view-toggle')),handle:rect(document.getElementById('o-stop-handle')),
    thickness_input:rect(document.querySelector('[data-key="L0thickness"] .o-current')),
    chief_toggle:rect(document.getElementById('o-ray-chief')),viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},
    conditions_label:document.getElementById('o-ray-conditions')?.textContent||'',
    _geometry:JSON.stringify({lenses:state.lenses,source:state.source,gaps:state.gaps}),_paths:grouped};
})()"""


def digest(value):
    return hashlib.sha256((value if isinstance(value,str) else json.dumps(value,sort_keys=True)).encode()).hexdigest()


class ChiefPointerRunner(StopPointerRunner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.result['kind']='actual-QtTest-chief-and-attached-stop-QA'
        self.result['input_method']='QtTest QWidget numeric-input keys, pointer drag and checkbox/toggle clicks'
        self.result.pop('js_state_mutation',None)
        self.result['application_state_assigned_via_js']=False

    def snapshot(self,name):
        state=self.evaluate(SNAPSHOT)
        state['geometry_fingerprint']=digest(state.pop('_geometry'))
        state['path_fingerprints']={kind:digest(paths) for kind,paths in state.pop('_paths').items()}
        self.result['states'][name]=state
        return state

    def edit_thickness(self,before):
        self.click_rect(before['thickness_input'],before,'focus_L1_thickness_via_QTest')
        target=self.view.focusProxy() or self.view
        QTest.keySequence(target,QKeySequence(QKeySequence.StandardKey.SelectAll))
        text=format(before['thickness']+.5,'.15g')
        QTest.keyClicks(target,text)
        QTest.keyClick(target,Qt.Key.Key_Tab)
        QTest.qWait(220)
        self.result['actions'].append({'action':'QTest_type_thickness_and_Tab','old_mm':before['thickness'],'typed_mm':text})
        return self.snapshot('after_thickness_edit')

    def drag_stop(self,before):
        handle=before['handle'];x,y=handle['x']+handle['width']/2,handle['y']+handle['height']/2
        start,a=self.point(x,y,before);end,b=self.point(x+35,y,before)
        target,p0=self.target_point(start);_,p1=self.target_point(end)
        QTest.mouseMove(target,p0,10)
        QTest.mousePress(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p0,20)
        QTest.qWait(30)
        for i in range(1,8):
            QTest.mouseMove(target,QPoint(round(p0.x()+(p1.x()-p0.x())*i/7),p0.y()),10)
            QTest.qWait(20)
        QTest.mouseRelease(target,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p1,20)
        QTest.qWait(200)
        self.result['actions'].append({'action':'QTest_manual_stop_drag','start':a,'end':b})
        return self.snapshot('after_manual_drag')

    def run_checks(self):
        try:
            self.evaluate("(()=>{window.__CHIEF_QA_INPUT__={};for(const type of ['pointerdown','pointermove','pointerup','keydown','input','change'])document.addEventListener(type,e=>{if(e.isTrusted)window.__CHIEF_QA_INPUT__[type]=true;},true);return true;})()")
            initial=self.snapshot('initial_3d')
            self.click_rect(initial['toggle'],initial,'open_2d_via_QTest')
            before=self.snapshot('initial_2d')
            stop=before['stop'];preview=before['preview_stop']
            self.check('default_surface6_stop_at_L3_rear_and_csd',stop['position_mode']=='surface' and stop['surface_index']==6 and abs(before['plane_z']-before['expected_rear_z'])<1e-8 and abs(preview['semi_diameter_mm']-before['expected_rear_csd'])<1e-8,
                       {'z_mm':before['plane_z'],'expected_z_mm':before['expected_rear_z'],'csd_mm':preview['semi_diameter_mm']})
            kinds=[ray['kind'] for ray in before['rays']]
            self.check('chief_one_and_marginal_two_only',before['ray_counts']=={'chief':1,'marginal':2} and kinds.count('chief')==1 and kinds.count('marginal')==2 and set(kinds)<={'chief','marginal'} and before['paths_finite'] and all(r['finite'] and r['status']=='ok' for r in before['rays']),
                       {'rendered_counts':before['ray_counts'],'ray_kinds':kinds})
            chief=next(ray for ray in before['rays'] if ray['kind']=='chief')
            self.check('chief_exact_axis_stop_center_to_image_zero',chief['on_axis'] and chief['passes_stop_center'] and abs(chief['end_z'])<1e-9 and abs(chief['image_height_mm'])<1e-9 and before['image_z_mm']==0)
            followed=self.edit_thickness(before)
            self.check('real_thickness_edit_moves_attached_stop_by_half_mm',abs(followed['thickness']-before['thickness']-.5)<1e-8 and abs(followed['plane_z']-before['plane_z']-.5)<1e-8 and followed['stop']['position_mode']=='surface' and followed['stop']['surface_index']==6,
                       {'thickness_before':before['thickness'],'thickness_after':followed['thickness'],'stop_before':before['plane_z'],'stop_after':followed['plane_z']})
            self.result['attached_screenshot_saved']=self.view.grab().save(str(self.output/'chief-surface-stop.png'))
            self.click_rect(followed['chief_toggle'],followed,'uncheck_chief_via_QTest')
            hidden=self.snapshot('chief_hidden')
            self.check('chief_checkbox_hides_only_chief',hidden['ray_counts'].get('chief',0)==0 and hidden['ray_counts'].get('marginal')==2 and hidden['path_fingerprints']['marginal']==followed['path_fingerprints']['marginal'])
            self.click_rect(hidden['chief_toggle'],hidden,'restore_chief_via_QTest')
            both=self.snapshot('chief_restored')
            self.click_rect(both['toggle'],both,'return_3d_via_QTest')
            three=self.snapshot('back_in_3d')
            self.check('3d_hides_ray_overlay_and_controls',not three['section'] and not three['overlay_visible'] and not three['tools_visible'])
            self.click_rect(three['toggle'],three,'return_2d_via_QTest')
            attached=self.snapshot('attached_before_drag')
            dragged=self.drag_stop(attached)
            self.check('manual_drag_detaches_and_retains_surface6',dragged['stop']['position_mode']=='absolute' and dragged['stop']['surface_index']==6 and dragged['plane_z']>attached['plane_z'] and dragged['geometry_fingerprint']==attached['geometry_fingerprint'])
            trusted=self.evaluate('window.__CHIEF_QA_INPUT__')
            self.result['trusted_inputs']=trusted
            self.check('native_inputs_clean_js_and_attached_capture',all(trusted.get(kind) for kind in ('pointerdown','pointermove','pointerup','keydown','input','change')) and self.stats['javascript_errors']==0 and self.result['attached_screenshot_saved'])
            self.finish()
        except Exception as error:
            self.fail(error)

    def fail(self,error):
        self.result['error']={'type':type(error).__name__,'message':str(error)}
        self.finish()

    def finish(self):
        self.result['seconds']=time.monotonic()-self.started
        self.result['resource_policy']=dict(self.stats)
        self.result['actual_content_size']=[self.view.width(),self.view.height()]
        self.result['final_screenshot_saved']=self.view.grab().save(str(self.output/'chief-after-drag.png'))
        self.result['passed']=bool(self.checks) and all(check['pass'] for check in self.checks) and 'error' not in self.result
        self.exit_code=0 if self.result['passed'] else 1
        (self.output/'results.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Chief GUI smoke:','PASS' if self.exit_code==0 else 'FAIL',str(self.output/'results.json'),flush=True)
        self.window.close_for_shutdown()
        QTimer.singleShot(0,self.app.quit)


def main():
    parser=argparse.ArgumentParser(description='Opt-in native Chief and Stop-follow GUI QA')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/chief-smoke')
    args=parser.parse_args()
    desktop.SmokeRunner=ChiefPointerRunner
    return desktop.main(['--smoke','--output-dir',str(args.output_dir.resolve())])


if __name__=='__main__':
    raise SystemExit(main())

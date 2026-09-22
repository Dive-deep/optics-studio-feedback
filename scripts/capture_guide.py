"""Capture the real review app with bundled synthetic data for the static guide."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optics_ui import desktop
from PySide6.QtCore import QTimer

IMAGES = ROOT / 'guide/dist/images'
IMAGES.mkdir(parents=True, exist_ok=True)


class GuideCapture(desktop.SmokeRunner):
    SCRIPT = r'''
    (async()=>{
      const wait=async predicate=>{for(let i=0;i<600;i++){if(predicate())return;await new Promise(r=>setTimeout(r,25))}throw new Error('Guide data timeout')};
      const action=name=>document.querySelector('[data-action="'+name+'"]').click();
      action('model');document.querySelector('#o-report-browse').click();
      await wait(()=>document.querySelector('[data-action="model"]').textContent.includes('demo-model.pth'));
      action('targets');document.querySelector('#o-target-browse').click();
      await wait(()=>document.querySelector('#o-target-json'));
      action('workspace');
      window.__DESKTOP_SMOKE_RESULT__={checks:[{name:'guide_loaded_real_demo_report',pass:true},{name:'guide_loaded_real_target',pass:true}]};
    })().catch(error=>{window.__DESKTOP_SMOKE_RESULT__={checks:[{name:'guide_ready',pass:false}],error:String(error)}});
    '''

    def capture(self, index=0):
        scenarios = [
            ('workspace.png', "document.querySelector('[data-action=workspace]').click()"),
            ('section.png', "document.querySelector('#o-view-toggle').click()"),
            ('simulation.png', "document.querySelector('[data-action=sim]').click()"),
            ('model.png', "document.querySelector('[data-action=update]').click()"),
        ]
        if index >= len(scenarios):
            self.evidence['compute_panel_capture'] = {'status': 'hook_unavailable'}
            self.finish()
            return
        name, script = scenarios[index]
        view = self.window.centralWidget()
        view.setFixedSize(1600, 1080)
        self.window.adjustSize()
        def ready(_):
            def shot():
                saved = view.grab().save(str(IMAGES / name))
                self.evidence['captures'].append({'file': name, 'saved': saved, 'source': 'real Qt app with bundled synthetic DB', 'size':[view.width(),view.height()]})
                self.capture(index+1)
            QTimer.singleShot(850, shot)
        self.page.runJavaScript(script, ready)


def main():
    desktop.SmokeRunner = GuideCapture
    return desktop.main(['--smoke','--output-dir',str(ROOT/'artifacts/guide-capture'),
        '--smoke-report',str(ROOT/'examples/local-demo/training-report.json'),
        '--smoke-target',str(ROOT/'examples/local-demo/target.json')])


if __name__=='__main__':
    raise SystemExit(main())

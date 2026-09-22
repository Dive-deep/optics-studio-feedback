# Third-party notices and demonstration data

The Python interpreter, PySide6/Qt, and their binary dependencies are **not bundled**. Users install the pinned direct dependency from `requirements.txt`; its transitive wheels and license notices come from the upstream distribution.

- PySide6 6.11.2: <https://pypi.org/project/PySide6/6.11.2/>. See upstream licensing and installed package notices.
- Qt for Python installation: <https://doc.qt.io/qtforpython-6/gettingstarted.html>.

## Local web assets included with the UI

These browser assets are necessary to render the offline UI. Their complete notices remain beside the files.

| Component | Version | Notice |
|---|---|---|
| D3 | 7.9.0 | `optics_ui/assets/vendor/d3-LICENSE` (ISC) |
| Lucide | 1.42.0 | `optics_ui/assets/vendor/lucide-LICENSE` (ISC and included Feather MIT notice) |
| Three.js / OrbitControls | 0.180.0 | `optics_ui/assets/vendor/three/LICENSE` (MIT) |

The source repository also retains original vendor files and version/hash metadata for reproducible development. The feedback ZIP includes the runtime web assets only, without duplicating vendor source trees.

## Demonstration data

`examples/local-demo/demo-cases.sqlite` contains synthetic mathematical proxies, not Zemax measurements. `demo-model.pth` is a 195-byte opaque file-loading fixture, not trained surrogate weights. It is never deserialized as a model in this UI.

The material catalog retains its original sources, proxy warnings and eligibility metadata. Manufacturer names identify referenced data sources; they do not indicate endorsement, a validated production optical model, or permission broader than the original records. Fields such as `referenced_only` and `release_eligible=0` are preserved as data and must not be relabeled as a distribution license or manufacturing approval.

Screenshots in the guide are captures of this UI with synthetic demonstration data on the Mac development host. They are not Windows workstation, Zemax or optical-performance validation evidence.

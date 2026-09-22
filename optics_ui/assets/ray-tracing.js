/* Meridional geometrical preview, not Zemax results or a performance predictor.
 * World prescription keeps +z radius signs; light travels from +z toward 0.
 * Exact refraction uses vector Snell; paraxial transfer uses reverse curvature.
 * Vector Snell derivation:
 * https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading/reflection-refraction-fresnel.html
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OpticsRays = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const POWERS = [4, 6, 8, 10, 12];
  const ROOT_STEPS = 64, ROOT_ITERATIONS = 64, AIM_STEPS = 128;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const apertureTolerance = aperture => aperture * 1e-9;
  const diagnostic = (code, message) => ({code, message});

  function shape(surface, y) {
    const c = surface.curvature, q = 1 - (1 + surface.conic) * c * c * y * y;
    if (!(q > 0)) return null;
    const squareRoot = Math.sqrt(q);
    let sag = c * y * y / (1 + squareRoot), derivative = c * y / squareRoot;
    for (let j = 0; j < POWERS.length; j++) {
      const power = POWERS[j], coefficient = surface.coefficients[j];
      if (coefficient !== 0) {
        sag += coefficient * y ** power;
        derivative += power * coefficient * y ** (power - 1);
      }
    }
    return finite(sag) && finite(derivative) ? {sag, derivative} : null;
  }

  function bounds(surface) {
    const c = surface.curvature, a = surface.aperture;
    const q = 1 - (1 + surface.conic) * c * c * a * a;
    if (!(q > 0)) return null;
    const base = c * a * a / (1 + Math.sqrt(q));
    let lower = Math.min(0, base), upper = Math.max(0, base);
    // Conservative polynomial bounds over [-aperture, aperture], including
    // nonmonotonic even aspheres. Do not bound only by edge sag.
    for (let j = 0; j < POWERS.length; j++) {
      const term = surface.coefficients[j] * a ** POWERS[j];
      lower += Math.min(0, term); upper += Math.max(0, term);
    }
    const min = surface.vertex + lower, max = surface.vertex + upper;
    return finite(min) && finite(max) && shape(surface, a) ? {min, max} : null;
  }

  function invalid(status, code, message) {
    return {status, rays: [], stop: {z_mm: null, semi_diameter_mm: null, mode: null},
      start_z_mm: null, image_z_mm: 0, diagnostics: [diagnostic(code, message)]};
  }

  function prepare(optics, indices) {
    const fail = message => ({error: invalid('invalid_geometry', 'INVALID_GEOMETRY', message)});
    if (!optics || !finite(optics.source) || optics.source < 0 || !Array.isArray(optics.lenses)
        || optics.lenses.length < 1 || optics.lenses.length > 3) return fail('유효한 유한 거리 광학계가 필요합니다.');
    const surfaces = [], lensRanges = [];
    let vertex = optics.source;
    for (let lensIndex = 0; lensIndex < optics.lenses.length; lensIndex++) {
      const lens = optics.lenses[lensIndex];
      if (!lens || !['STANDARD', 'EVEN_ASPHERE'].includes(lens.type) || !finite(lens.thickness)
          || lens.thickness <= 0 || !Array.isArray(lens.surfaces) || lens.surfaces.length !== 2) return fail('렌즈 두께·표면 정의가 유효하지 않습니다.');
      const index = indices && Object.hasOwn(indices, lens.material) ? indices[lens.material] : null;
      if (!finite(index) || index <= 0) return {error: invalid('missing_index', 'MISSING_REFRACTIVE_INDEX', '현재 재질의 선택 파장·온도 굴절률이 없습니다: ' + String(lens.material))};
      const pair = [];
      for (let side = 0; side < 2; side++) {
        const raw = lens.surfaces[side];
        if (!raw || !finite(raw.radius) || !finite(raw.conic) || !finite(raw.aperture) || raw.aperture <= 0) return fail('반경·Conic·clear semi-diameter가 유효하지 않습니다.');
        const coefficients = POWERS.map(power => lens.type === 'STANDARD' ? 0 :
          power === 12 && raw.a12 == null ? 0 : raw['a' + power]);
        if (!coefficients.every(finite)) return fail('비구면 계수에 유효하지 않은 값이 있습니다.');
        const surface = {vertex: vertex + (side ? lens.thickness : 0), aperture: raw.aperture,
          curvature: raw.radius === 0 ? 0 : 1 / raw.radius, conic: raw.conic, coefficients,
          index: surfaces.length + 1, nFrom: side ? 1 : index, nTo: side ? index : 1};
        const range = bounds(surface);
        if (!range) return fail('clear aperture에서 실수 sag/법선을 만들 수 없습니다.');
        surface.min = range.min; surface.max = range.max;
        surfaces.push(surface); pair.push(surface);
      }
      lensRanges.push({min: Math.min(pair[0].min, pair[1].min), max: Math.max(pair[0].max, pair[1].max)});
      vertex += lens.thickness;
      if (lensIndex < optics.lenses.length - 1) {
        const gap = optics.gaps && optics.gaps[lensIndex === 0 ? 'gap12' : 'gap23'];
        if (!finite(gap) || gap < 0) return fail('렌즈 간격이 유효하지 않습니다.');
        vertex += gap;
      }
    }
    // Domain check plus a bounded profile-separation check; every traced ray
    // additionally verifies the actual next forward intersection.
    for (let i = 1; i < surfaces.length; i++) {
      const previous = surfaces[i - 1], next = surfaces[i], aperture = Math.min(previous.aperture, next.aperture);
      for (let j = 0; j <= 128; j++) {
        const y = aperture * j / 128, a = shape(previous, y), b = shape(next, y);
        if (!a || !b || next.vertex + b.sag < previous.vertex + a.sag - 1e-9) return fail('렌즈 면 또는 인접 렌즈가 교차합니다.');
      }
    }
    const rawStop = optics.stop || {position_mode: 'surface', surface_index: surfaces.length, z_mm: null};
    const stopIndex = rawStop.surface_index === undefined ? surfaces.length : rawStop.surface_index;
    if (!['surface', 'absolute'].includes(rawStop.position_mode) || !Number.isInteger(stopIndex)
        || stopIndex < 1 || stopIndex > surfaces.length) return {error: invalid('invalid_stop_position', 'INVALID_STOP_POSITION', '지원하지 않는 조리개 위치 정의입니다.')};
    const boundSurface = surfaces[stopIndex - 1], stop = {mode: rawStop.position_mode, z_mm: boundSurface.vertex,
      semi_diameter_mm: boundSurface.aperture, surface_index: stopIndex,
      edge_z_mm: boundSurface.vertex + shape(boundSurface, boundSurface.aperture).sag};
    if (stop.mode === 'absolute') {
      stop.z_mm = rawStop.z_mm; stop.edge_z_mm = rawStop.z_mm;
      if (!finite(stop.z_mm) || stop.z_mm < 0 || lensRanges.some(range => stop.z_mm >= range.min - 1e-9 && stop.z_mm <= range.max + 1e-9)) {
        return {error: invalid('invalid_stop_position', 'INVALID_STOP_POSITION', '조리개 평면이 유리 또는 곡면의 z 범위와 겹칩니다. 공기 구간에 놓거나 표면 조리개를 사용하세요.')};
      }
    }
    const maximum = Math.max(stop.z_mm, ...surfaces.map(surface => surface.max));
    const minimumAperture = Math.min(...surfaces.map(surface => surface.aperture));
    const start = maximum + Math.max(2, minimumAperture * .5, maximum * .08);
    if (!finite(start) || !finite(stop.edge_z_mm)) return fail('광학계 크기가 수치 계산 범위를 벗어납니다.');
    return {surfaces, stop, start, minimumAperture, entranceAperture: surfaces.at(-1).aperture,
      tolerance: 1e-9 * Math.max(1, Math.min(start, 1000))};
  }

  function intersection(surface, point, direction, tolerance) {
    if (direction.z >= -1e-12) return {status: 'reversed'};
    const low = Math.max(0, (point.z - surface.max) / -direction.z);
    const high = (point.z - surface.min) / -direction.z;
    if (!finite(low) || !finite(high) || high < low - tolerance) return {status: 'intersection_failed'};
    const at = t => {
      const z = point.z + direction.z * t, y = point.y + direction.y * t;
      if (!finite(z) || !finite(y)) return null;
      const value = shape(surface, y);
      return value ? {z, y, t, derivative: value.derivative, residual: z - surface.vertex - value.sag} : null;
    };
    const valid = value => value && Math.abs(value.y) <= surface.aperture + apertureTolerance(surface.aperture);
    const hit = value => ({status: 'ok', point: {z: value.z, y: value.y}, derivative: value.derivative});
    // A horizontal on-axis input or a plane has an analytic intersection.
    if (Math.abs(direction.y) < 1e-15) {
      const value = shape(surface, point.y);
      if (value) {
        const t = (point.z - surface.vertex - value.sag) / -direction.z, valueAt = at(t);
        if (t >= -tolerance && valid(valueAt)) return hit(valueAt);
      }
    }
    let previous = null;
    for (let j = 0; j <= ROOT_STEPS; j++) {
      const value = at(low + (high - low) * j / ROOT_STEPS);
      if (!valid(value)) { previous = null; continue; }
      if (Math.abs(value.residual) <= tolerance) return hit(value);
      if (previous && previous.residual * value.residual < 0) {
        let left = previous, right = value;
        for (let iteration = 0; iteration < ROOT_ITERATIONS; iteration++) {
          const middle = at((left.t + right.t) / 2);
          if (!valid(middle)) return {status: 'intersection_failed'};
          if (Math.abs(middle.residual) <= tolerance) return hit(middle);
          if (left.residual * middle.residual <= 0) right = middle; else left = middle;
        }
        const middle = at((left.t + right.t) / 2);
        if (valid(middle) && Math.abs(middle.residual) <= tolerance * 8) return hit(middle);
        return {status: 'intersection_failed'};
      }
      previous = value;
    }
    // Show a failed aperture encounter, never continue this ray to the image.
    const t = (point.z - surface.vertex) / -direction.z, estimate = at(t);
    if (finite(t) && t >= -tolerance) {
      const end = {z: surface.vertex, y: point.y + direction.y * t};
      if (finite(end.y) && (Math.abs(end.y) > surface.aperture + apertureTolerance(surface.aperture) || !estimate)) return {status: 'clipped', point: end, approximate_endpoint: true};
    }
    return {status: 'intersection_failed'};
  }

  function refract(direction, derivative, nFrom, nTo) {
    const length = Math.hypot(1, derivative), normal = {z: 1 / length, y: -derivative / length};
    const cosine = -(direction.z * normal.z + direction.y * normal.y);
    if (!(cosine > 1e-12)) return {status: 'reversed'};
    const ratio = nFrom / nTo, incidentSine = Math.sqrt(Math.max(0, 1 - cosine * cosine));
    const k = 1 - ratio * ratio * incidentSine * incidentSine;
    if (k < -1e-12) return {status: 'tir'};
    const coefficient = ratio * cosine - Math.sqrt(Math.max(0, k));
    const z = ratio * direction.z + coefficient * normal.z, y = ratio * direction.y + coefficient * normal.y;
    const norm = Math.hypot(z, y);
    if (!finite(norm) || norm === 0) return {status: 'intersection_failed'};
    const next = {z: z / norm, y: y / norm};
    return {status: next.z < -1e-12 ? 'ok' : 'reversed', direction: next,
      incidence_sine: incidentSine, refracted_sine: ratio * incidentSine};
  }

  function eventsFor(model, aiming) {
    const events = model.surfaces.slice().reverse().map(surface => ({surface, z: surface.vertex}));
    if (model.stop.mode === 'absolute') {
      events.push({isStop: true, z: model.stop.z_mm});
      // This plane was proved disjoint from conservative surface/glass bounds.
      return events.sort((a, b) => b.z - a.z);
    }
    else if (aiming) {
      // To aim at the actual stop edge, intersect the preceding ray with the
      // known edge-z plane. This avoids extending the stop clear aperture.
      // The final candidate is retraced against the real curved stop surface.
      const stopEventIndex = events.findIndex(event => event.surface.index === model.stop.surface_index);
      // Retain only interfaces encountered BEFORE the selected stop surface.
      // Surface 6 has no preceding interface; surface 3 has 6 -> 5 -> 4.
      events.splice(stopEventIndex, events.length - stopEventIndex,
        {isStop: true, z: model.stop.edge_z_mm});
    }
    // A curved stop edge may be to the right of the preceding vertex plane
    // (valid thin meniscus). Actual surfaces retain their sequential order;
    // its virtual aiming plane must remain AFTER the preceding interface.
    return events;
  }

  function exact(model, height, angle = 0, aiming = false) {
    const ray = {kind: 'reference', status: 'ok', launch_height_mm: finite(height) ? height : null,
      points: [], interactions: [], method: 'meridional_snell'};
    if (!finite(height) || !finite(angle) || Math.abs(angle) >= Math.PI / 2) return {...ray, status: 'invalid_geometry', diagnostic_code: 'INVALID_LAUNCH'};
    let point = {z: model.start, y: height}, direction = {z: -Math.cos(angle), y: Math.sin(angle)};
    ray.points.push({...point});
    const fail = (status, surface, endpoint) => {
      if (endpoint && finite(endpoint.z) && finite(endpoint.y)) ray.points.push({...endpoint, ...(surface ? {surface_index: surface.index} : {})});
      ray.status = status; ray.direction = {...direction};
      if (surface) ray.failed_surface_index = surface.index;
      return ray;
    };
    for (const event of eventsFor(model, aiming)) {
      if (event.isStop) {
        const distance = (point.z - event.z) / -direction.z;
        if (direction.z >= -1e-12 || distance < -model.tolerance || !finite(distance)) return fail('reversed');
        point = {z: event.z, y: point.y + direction.y * distance};
        if (!finite(point.y)) return fail('intersection_failed');
        ray.stop_height_mm = point.y; ray.stop_point = {...point}; ray.points.push({...point, stop: true});
        if (aiming) {ray.direction = {...direction}; return ray;}
        if (Math.abs(point.y) > model.stop.semi_diameter_mm + apertureTolerance(model.stop.semi_diameter_mm)) return fail('clipped');
        continue;
      }
      const surface = event.surface, encounter = intersection(surface, point, direction, model.tolerance);
      if (encounter.status !== 'ok') {
        if (encounter.approximate_endpoint) ray.approximate_failure_endpoint = true;
        return fail(encounter.status, surface, encounter.point);
      }
      point = encounter.point; ray.points.push({...point, surface_index: surface.index});
      if (model.stop.mode === 'surface' && surface.index === model.stop.surface_index) {
        ray.stop_height_mm = point.y; ray.stop_point = {...point}; ray.points.at(-1).stop = true;
      }
      const next = refract(direction, encounter.derivative, surface.nFrom, surface.nTo);
      if (next.status !== 'ok') return fail(next.status, surface);
      ray.interactions.push({surface_index: surface.index, n_from: surface.nFrom, n_to: surface.nTo,
        incidence_sine: next.incidence_sine, refracted_sine: next.refracted_sine});
      direction = next.direction;
    }
    if (direction.z >= -1e-12 || point.z < -model.tolerance) return fail('reversed');
    const y = point.y + direction.y * point.z / -direction.z;
    if (!finite(y)) return fail('intersection_failed');
    ray.points.push({z: 0, y, image: true}); ray.image_height_mm = y; ray.direction = {...direction};
    return ray;
  }

  function paraxial(model, height) {
    const ray = {kind: 'paraxial', status: 'ok', launch_height_mm: finite(height) ? height : null, method: 'paraxial_transfer', points: [{z: model.start, y: height}]};
    if (!finite(height)) return {...ray, status: 'invalid_geometry', points: []};
    let z = model.start, y = height, u = 0;
    const events = model.surfaces.slice().reverse().map(surface => ({surface, z: surface.vertex}));
    if (model.stop.mode === 'absolute') events.push({isStop: true, z: model.stop.z_mm});
    events.sort((a, b) => b.z - a.z);
    for (const event of events) {
      y += (z - event.z) * u; z = event.z;
      if (!finite(y)) return {...ray, status: 'intersection_failed'};
      ray.points.push({z, y, ...(event.surface ? {surface_index: event.surface.index} : {stop: true})});
      const aperture = event.isStop ? model.stop.semi_diameter_mm : event.surface.aperture;
      if (Math.abs(y) > aperture + apertureTolerance(aperture)) return {...ray, status: 'clipped'};
      if (event.isStop || model.stop.mode === 'surface' && event.surface.index === model.stop.surface_index) {
        ray.stop_height_mm = y; ray.stop_point = {z, y};
      }
      if (event.surface) {
        const s = event.surface;
        // u = dy/d(distance travelled toward -z). R_reverse = -R_world.
        u = s.nFrom / s.nTo * u + (s.nTo - s.nFrom) / s.nTo * s.curvature * y;
      }
      if (!finite(u)) return {...ray, status: 'intersection_failed'};
    }
    y += z * u;
    if (!finite(y)) return {...ray, status: 'intersection_failed'};
    ray.points.push({z: 0, y, image: true}); ray.image_height_mm = y;
    const norm = Math.hypot(1, u); ray.direction = {z: -1 / norm, y: u / norm};
    return ray;
  }

  function aim(model, target) {
    const tolerance = Math.max(Number.EPSILON * model.entranceAperture * 32, model.stop.semi_diameter_mm * 1e-8);
    const evaluate = height => {
      const ray = exact(model, height, 0, true);
      return finite(ray.stop_height_mm) ? {height, residual: ray.stop_height_mm - target} : null;
    };
    const candidates = []; let previous = null;
    for (let j = 0; j <= AIM_STEPS; j++) {
      const current = evaluate(-model.entranceAperture + 2 * model.entranceAperture * j / AIM_STEPS);
      if (!current) {previous = null; continue;}
      if (Math.abs(current.residual) <= tolerance) candidates.push(current.height);
      if (previous && previous.residual * current.residual < 0) {
        let left = previous, right = current;
        for (let iteration = 0; iteration < ROOT_ITERATIONS; iteration++) {
          const middle = evaluate((left.height + right.height) / 2);
          if (!middle) break;
          if (Math.abs(middle.residual) <= tolerance * .01) {candidates.push(middle.height); break;}
          if (left.residual * middle.residual <= 0) right = middle; else left = middle;
        }
      }
      previous = current;
    }
    candidates.sort((a, b) => Math.abs(a) - Math.abs(b));
    for (const height of candidates) {
      const ray = exact(model, height);
      if (finite(ray.stop_height_mm) && Math.abs(ray.stop_height_mm - target) <= tolerance) {
        return {...ray, kind: 'marginal', target_stop_height_mm: target};
      }
    }
    return {kind: 'marginal', status: 'unreachable', method: 'meridional_snell',
      target_stop_height_mm: target, points: [], diagnostic_code: 'STOP_UNREACHABLE'};
  }

  function traceSection(optics, indices) {
    const model = prepare(optics, indices);
    if (model.error) return model.error;
    // Centered 0F input: the chief is the exact on-axis ray through the stop
    // center. Do not invent a nonzero launch angle to make it visually distinct.
    const a = model.stop.semi_diameter_mm, rays = [ {...exact(model, 0), kind: 'chief',
      target_stop_height_mm: 0, field_norm: 0},
      aim(model, -a), aim(model, a) ];
    const diagnostics = [];
    const marginal = rays.filter(ray => ray.kind === 'marginal');
    if (marginal.some(ray => ray.status === 'unreachable')) diagnostics.push(diagnostic('STOP_UNREACHABLE', '다른 clear aperture를 유지한 제한된 launch-height 탐색에서 조리개 가장자리에 도달하는 광선을 찾지 못했습니다. 참고 광선은 marginal ray가 아닙니다.'));
    if (marginal.some(ray => !['ok', 'unreachable'].includes(ray.status))) diagnostics.push(diagnostic('MARGINAL_VIGNETTED', '조리개 가장자리 광선이 이후 면에서 차단되거나 굴절을 완료하지 못했습니다.'));
    if (marginal.some(ray => ray.status !== 'ok')) {
      for (const fraction of [-.75, -.5, -.25, .25, .5, .75]) rays.push({...exact(model, model.entranceAperture * fraction), kind: 'reference'});
    }
    return {status: rays.every(ray => ray.status === 'ok') ? 'ok' : 'partial', rays,
      stop: {...model.stop}, start_z_mm: model.start, image_z_mm: 0, diagnostics,
      geometry_check: 'surface_domains_and_sampled_separation_with_per_ray_intersections',
      propagation: 'positive_z_to_image_zero', performance_prediction: false};
  }

  function traceRay(optics, indices, options = {}) {
    const model = prepare(optics, indices);
    if (model.error) return {kind: 'reference', status: model.error.status, points: [], diagnostics: model.error.diagnostics};
    return exact(model, options.launch_height_mm ?? 0, options.angle_rad ?? 0);
  }

  function traceParaxial(optics, indices, options = {}) {
    const model = prepare(optics, indices);
    if (model.error) return {kind: 'paraxial', status: model.error.status, points: [], diagnostics: model.error.diagnostics};
    return paraxial(model, options.launch_height_mm ?? model.minimumAperture * .04);
  }

  return {traceSection, traceRay, traceParaxial};
});

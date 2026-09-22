CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO metadata VALUES ('database_id','db-a'),('schema_version','1.0.0'),('material_catalog_path','materials/catalog.sqlite');
CREATE TABLE designs (design_id TEXT PRIMARY KEY, family_id TEXT, source_distance_mm REAL, geometry_valid INTEGER, trace_success INTEGER, overall_status TEXT, data_origin TEXT, zemax_executed INTEGER);
INSERT INTO designs VALUES ('D1','F1',9.5,1,1,'SUCCESS','SYNTHETIC_MATH_PROXY',0),('D2','F2',10.5,0,0,'FAILED','SYNTHETIC_MATH_PROXY',0);
CREATE TABLE lens_elements (design_id TEXT,lens_index INTEGER,material_id TEXT,center_thickness_mm REAL,front_surface_index INTEGER,back_surface_index INTEGER);
INSERT INTO lens_elements VALUES ('D1',1,'BK7',3.5,1,2),('D1',2,'BK7',4.5,3,4),('D1',3,'SF6',5.5,5,6);
CREATE TABLE surfaces (design_id TEXT,surface_index INTEGER,lens_index INTEGER,side TEXT,surface_type TEXT,radius_mm REAL,curvature_1_per_mm REAL,conic REAL,clear_semi_diameter_mm REAL,vertex_z_mm REAL,raw_surface_json TEXT);
INSERT INTO surfaces VALUES
('D1',1,1,'FRONT','STANDARD',50,0.02,0,15.5,0,'{"a4":0,"a6":0,"a8":0,"a10":0}'),
('D1',2,1,'BACK','STANDARD',-60,-0.016666666666666666,0,15.5,3.5,'{"a4":0,"a6":0,"a8":0,"a10":0}'),
('D1',3,2,'FRONT','EVEN_ASPHERE',70,0.014285714285714285,-0.3,15.5,6.5,'{"a4":0.000001,"a6":0,"a8":0,"a10":0}'),
('D1',4,2,'BACK','EVEN_ASPHERE',-80,-0.0125,-0.2,15.5,11,'{"a4":0,"a6":0,"a8":0,"a10":0}'),
('D1',5,3,'FRONT','STANDARD',90,0.011111111111111112,0,15.5,14,'{"a4":0,"a6":0,"a8":0,"a10":0}'),
('D1',6,3,'BACK','STANDARD',-100,-0.01,0,15.5,19.5,'{"a4":0,"a6":0,"a8":0,"a10":0}');
CREATE TABLE air_gaps (design_id TEXT,gap_index INTEGER,nominal_vertex_gap_mm REAL);
INSERT INTO air_gaps VALUES ('D1',1,3),('D1',2,3);
CREATE TABLE wavelengths (design_id TEXT,wavelength_no INTEGER,wavelength_nm REAL,weight REAL,is_primary INTEGER);
INSERT INTO wavelengths VALUES ('D1',1,486.1327,0.4,0),('D1',2,656.2725,0.6,1);
CREATE TABLE analyses (analysis_id TEXT,design_id TEXT,analysis_type TEXT,settings_json TEXT,execution_status TEXT,result_valid INTEGER,result_source TEXT);
INSERT INTO analyses VALUES ('A1','D1','FFT_MTF','{"temperature_c":20,"wavelengths_nm":[486.1327,656.2725],"wavelength_weights":[0.4,0.6]}','SUCCEEDED',1,'SYNTHETIC_PROXY'),('A2','D1','SPOT_DIAGRAM','{"temperature_c":20,"fields_norm":[0,1]}','SUCCEEDED',1,'SYNTHETIC_PROXY');
CREATE TABLE first_order_metrics (design_id TEXT,temperature_c REAL,image_space_na REAL,horizontal_fov_deg REAL,vertical_fov_deg REAL,distortion_percent_proxy REAL);
INSERT INTO first_order_metrics VALUES ('D1',20,0.44,24,6,1.2),('D1',25,0.43,23,5.9,1.3);
CREATE TABLE mtf_samples (design_id TEXT,temperature_c REAL,field_norm REAL,orientation TEXT,frequency_lp_per_mm REAL,mtf REAL);
INSERT INTO mtf_samples VALUES ('D1',20,0,'SAGITTAL',0,1),('D1',20,0,'SAGITTAL',6,0.5),('D1',25,0,'SAGITTAL',6,0.4);
CREATE TABLE spot_summary (design_id TEXT,temperature_c REAL,field_norm REAL,rms_radius_mm_proxy REAL,geometric_radius_mm_proxy REAL,ray_count INTEGER);
INSERT INTO spot_summary VALUES ('D1',20,1,0.0008,0.0016,2),('D1',20,0,0.0004,0.0008,2);
CREATE TABLE spot_points (design_id TEXT,temperature_c REAL,field_norm REAL,ray_index INTEGER,x_mm_proxy REAL,y_mm_proxy REAL);
INSERT INTO spot_points VALUES ('D1',20,1,0,-0.0008,0),('D1',20,1,1,0.0008,0),('D1',20,0,0,0.0004,0);

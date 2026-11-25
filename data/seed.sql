-- Fictional sample data. Company, carrier, and customer names are invented.
-- Designed around a fixed investigation date of 2026-03-16 (see INVESTIGATION_DATE).
--
-- Order guide (what each order is meant to exercise):
--   ORD-1001  pending, SKU-202 short at WH-BOS; WH-CHI alone can cover it      -> inventory shortage + transfer
--   ORD-1002  pending, SKU-404 short at WH-ATL; no single warehouse can cover  -> shortage, NO transfer
--   ORD-1003  shipped, carrier documented a storm delay, revised ETA           -> delayed delivery, confirmed cause
--   ORD-1004  shipped, overdue, no delay reason and no recent scan             -> delayed delivery, cause unknown
--   ORD-1005  shipped, in transit, ETA before promise date                     -> no exception
--   ORD-1006  delivered before promise date                                    -> no exception
--   ORD-1007  status SHIPPED but no shipment record exists                     -> missing information
--   ORD-1008  pending, 2 items: SKU-606 fine, SKU-303 short; WH-BOS can cover  -> multi-item shortage
--   ORD-1009  pending, enough stock, promise date in the future                -> no exception
--   ORD-1010  shipped, stuck at Toledo hub, no reason on shipment; carrier alert ALR-701 -> carrier disruption (suspected)
--   ORD-1011  shipped 4 days after its ship-by date; carrier moving normally   -> late warehouse dispatch
--   ORD-1012  pending, past promise; SKU-101 short at WH-CHI; BOS/DAL can cover -> shortage causing delay

INSERT INTO warehouses VALUES
  ('WH-BOS', 'Boston Distribution Center',  'Boston, MA'),
  ('WH-CHI', 'Chicago Distribution Center', 'Chicago, IL'),
  ('WH-ATL', 'Atlanta Distribution Center', 'Atlanta, GA'),
  ('WH-DAL', 'Dallas Distribution Center',  'Dallas, TX');

INSERT INTO products VALUES
  ('SKU-101', 'Pallet Jack Wheel Kit'),
  ('SKU-202', 'Industrial Shelf Bracket'),
  ('SKU-303', 'LED Panel Light 60W'),
  ('SKU-404', 'Handheld Barcode Scanner'),
  ('SKU-505', 'Stretch Wrap Roll'),
  ('SKU-606', 'Nitrile Safety Gloves (box of 100)');

INSERT INTO orders VALUES
  ('ORD-1001', 'Northwind Retail',    'WH-BOS', '2026-03-10', '2026-03-19', '2026-03-17', 'PENDING_FULFILLMENT'),
  ('ORD-1002', 'Bluebird Labs',       'WH-ATL', '2026-03-09', '2026-03-18', '2026-03-16', 'PENDING_FULFILLMENT'),
  ('ORD-1003', 'Contoso Hardware',    'WH-CHI', '2026-03-02', '2026-03-09', '2026-03-04', 'SHIPPED'),
  ('ORD-1004', 'Fabrikam Foods',      'WH-DAL', '2026-03-03', '2026-03-10', '2026-03-05', 'SHIPPED'),
  ('ORD-1005', 'Adventure Works',     'WH-BOS', '2026-03-12', '2026-03-20', '2026-03-13', 'SHIPPED'),
  ('ORD-1006', 'Tailspin Toys',       'WH-CHI', '2026-03-01', '2026-03-06', '2026-03-02', 'DELIVERED'),
  ('ORD-1007', 'Litware Inc',         'WH-ATL', '2026-03-08', '2026-03-13', '2026-03-09', 'SHIPPED'),
  ('ORD-1008', 'Woodgrove Clinic',    'WH-DAL', '2026-03-11', '2026-03-17', '2026-03-16', 'PENDING_FULFILLMENT'),
  ('ORD-1009', 'Proseware Logistics', 'WH-ATL', '2026-03-14', '2026-03-20', '2026-03-17', 'PENDING_FULFILLMENT'),
  ('ORD-1010', 'Fourth Coffee',       'WH-CHI', '2026-03-03', '2026-03-11', '2026-03-05', 'SHIPPED'),
  ('ORD-1011', 'Wide World Importers','WH-ATL', '2026-03-06', '2026-03-14', '2026-03-09', 'SHIPPED'),
  ('ORD-1012', 'Tailwind Traders',    'WH-CHI', '2026-03-08', '2026-03-15', '2026-03-12', 'PENDING_FULFILLMENT');

INSERT INTO order_items VALUES
  ('ORD-1001', 'SKU-202', 50),
  ('ORD-1002', 'SKU-404', 30),
  ('ORD-1003', 'SKU-303', 20),
  ('ORD-1004', 'SKU-505', 40),
  ('ORD-1005', 'SKU-101', 10),
  ('ORD-1006', 'SKU-606', 25),
  ('ORD-1007', 'SKU-101', 12),
  ('ORD-1008', 'SKU-606', 100),
  ('ORD-1008', 'SKU-303', 30),
  ('ORD-1009', 'SKU-505', 20),
  ('ORD-1010', 'SKU-606', 50),
  ('ORD-1011', 'SKU-202', 15),
  ('ORD-1012', 'SKU-101', 30);

-- (sku, warehouse_id, on_hand, reserved)   available = on_hand - reserved
INSERT INTO inventory VALUES
  ('SKU-101', 'WH-BOS',  40,  5),   -- 35
  ('SKU-101', 'WH-CHI',  20,  0),   -- 20
  ('SKU-101', 'WH-ATL',   0,  0),   --  0
  ('SKU-101', 'WH-DAL',  15,  0),   -- 15
  ('SKU-202', 'WH-BOS',  12,  0),   -- 12   ORD-1001 needs 50 -> short 38
  ('SKU-202', 'WH-CHI',  95, 15),   -- 80   only warehouse that can cover 50 (or 38)
  ('SKU-202', 'WH-ATL',  30,  0),   -- 30   not enough alone
  ('SKU-202', 'WH-DAL',   0,  0),   --  0
  ('SKU-303', 'WH-BOS',  60, 10),   -- 50   only warehouse that can cover ORD-1008's 30 (or shortfall 10)
  ('SKU-303', 'WH-CHI',  25, 20),   --  5
  ('SKU-303', 'WH-ATL',  18, 12),   --  6
  ('SKU-303', 'WH-DAL',  22,  2),   -- 20   ORD-1008 needs 30 -> short 10
  ('SKU-404', 'WH-BOS',   8,  0),   --  8
  ('SKU-404', 'WH-CHI',   6,  0),   --  6
  ('SKU-404', 'WH-ATL',  10,  2),   --  8   ORD-1002 needs 30 -> short 22
  ('SKU-404', 'WH-DAL',   5,  0),   --  5   (network total 27 < 30)
  ('SKU-505', 'WH-BOS', 200,  0),
  ('SKU-505', 'WH-CHI', 150, 10),
  ('SKU-505', 'WH-ATL', 120,  0),   -- ORD-1009 needs 20 -> fine
  ('SKU-505', 'WH-DAL',  90, 40),
  ('SKU-606', 'WH-BOS', 300,  0),
  ('SKU-606', 'WH-CHI', 180, 30),
  ('SKU-606', 'WH-ATL', 140,  0),
  ('SKU-606', 'WH-DAL', 250,  0);   -- ORD-1008 needs 100 -> fine

INSERT INTO shipments VALUES
  ('SHP-5003', 'ORD-1003', 'Great Lakes Freight', 'GLF-88231', 'DELAYED',
     '2026-03-04', '2026-03-09', '2026-03-18', NULL,
     'Carrier reported hub closure at Toledo, OH due to winter storm'),
  ('SHP-5004', 'ORD-1004', 'Lone Star Parcel',    'LSP-40417', 'IN_TRANSIT',
     '2026-03-05', '2026-03-10', NULL,         NULL, NULL),
  ('SHP-5005', 'ORD-1005', 'Harbor Express',      'HBX-11902', 'IN_TRANSIT',
     '2026-03-13', '2026-03-18', '2026-03-18', NULL, NULL),
  ('SHP-5006', 'ORD-1006', 'Great Lakes Freight', 'GLF-87950', 'DELIVERED',
     '2026-03-02', '2026-03-06', '2026-03-05', '2026-03-05', NULL),
  ('SHP-5010', 'ORD-1010', 'Great Lakes Freight', 'GLF-88307', 'IN_TRANSIT',
     '2026-03-05', '2026-03-11', NULL,         NULL, NULL),
  ('SHP-5011', 'ORD-1011', 'Harbor Express',      'HBX-12077', 'IN_TRANSIT',
     '2026-03-13', '2026-03-17', '2026-03-17', NULL, NULL);
-- Note: ORD-1007 is SHIPPED but intentionally has NO shipment row.

INSERT INTO shipment_events (shipment_id, event_date, location, event_type, description) VALUES
  ('SHP-5003', '2026-03-04', 'Chicago, IL', 'PICKED_UP',      'Picked up from WH-CHI'),
  ('SHP-5003', '2026-03-05', 'Gary, IN',    'IN_TRANSIT',     'Departed regional terminal'),
  ('SHP-5003', '2026-03-06', 'Toledo, OH',  'ARRIVED_AT_HUB', 'Arrived at Toledo hub'),
  ('SHP-5003', '2026-03-07', 'Toledo, OH',  'DELAY',          'Hub closed due to winter storm; revised ETA 2026-03-18'),
  ('SHP-5003', '2026-03-12', 'Toledo, OH',  'DEPARTED_HUB',   'Departed Toledo hub after reopening'),
  ('SHP-5004', '2026-03-05', 'Dallas, TX',  'PICKED_UP',      'Picked up from WH-DAL'),
  ('SHP-5004', '2026-03-07', 'Little Rock, AR', 'IN_TRANSIT', 'Departed sort facility'),
  ('SHP-5005', '2026-03-13', 'Boston, MA',  'PICKED_UP',      'Picked up from WH-BOS'),
  ('SHP-5005', '2026-03-15', 'Hartford, CT','IN_TRANSIT',     'Departed sort facility'),
  ('SHP-5006', '2026-03-02', 'Chicago, IL', 'PICKED_UP',      'Picked up from WH-CHI'),
  ('SHP-5006', '2026-03-05', 'Milwaukee, WI','DELIVERED',     'Delivered, signed by receiving dock'),
  ('SHP-5010', '2026-03-05', 'Chicago, IL', 'PICKED_UP',      'Picked up from WH-CHI'),
  ('SHP-5010', '2026-03-06', 'Gary, IN',    'IN_TRANSIT',     'Departed regional terminal'),
  ('SHP-5010', '2026-03-07', 'Toledo, OH',  'ARRIVED_AT_HUB', 'Arrived at Toledo hub'),
  ('SHP-5011', '2026-03-13', 'Atlanta, GA', 'PICKED_UP',      'Picked up from WH-ATL'),
  ('SHP-5011', '2026-03-14', 'Charlotte, NC','IN_TRANSIT',    'Departed sort facility'),
  ('SHP-5011', '2026-03-15', 'Richmond, VA','IN_TRANSIT',     'Departed sort facility');

-- Carrier service alerts. ALR-702 ended weeks ago and is irrelevant to current orders.
INSERT INTO carrier_alerts VALUES
  ('ALR-701', 'Great Lakes Freight', 'Toledo, OH',   '2026-03-06', '2026-03-13', 'HUB_CLOSURE',
     'Winter storm closed the Toledo hub; backlog of held freight being cleared through 2026-03-13'),
  ('ALR-702', 'Harbor Express',      'Hartford, CT', '2026-02-10', '2026-02-12', 'WEATHER',
     'Snow delays at Hartford sort facility');

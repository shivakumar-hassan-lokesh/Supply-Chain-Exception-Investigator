-- Supply Chain Exception Investigation Agent: database schema.
-- All data is fictional. Tools only ever READ from these tables.

DROP TABLE IF EXISTS carrier_alerts;
DROP TABLE IF EXISTS shipment_events;
DROP TABLE IF EXISTS shipments;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS warehouses;

CREATE TABLE warehouses (
    warehouse_id TEXT PRIMARY KEY,          -- e.g. WH-BOS
    name         TEXT NOT NULL,
    city         TEXT NOT NULL
);

CREATE TABLE products (
    sku  TEXT PRIMARY KEY,                  -- e.g. SKU-202
    name TEXT NOT NULL
);

CREATE TABLE orders (
    order_id               TEXT PRIMARY KEY, -- e.g. ORD-1003
    customer_name          TEXT NOT NULL,
    warehouse_id           TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    order_date             TEXT NOT NULL,    -- ISO date YYYY-MM-DD
    promised_delivery_date TEXT NOT NULL,    -- ISO date YYYY-MM-DD
    ship_by_date           TEXT NOT NULL,    -- date the warehouse planned to dispatch
    fulfillment_status     TEXT NOT NULL
        CHECK (fulfillment_status IN ('PENDING_FULFILLMENT', 'SHIPPED', 'DELIVERED'))
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    sku      TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, sku)
);

-- available = on_hand - reserved (computed by the tools, never stored)
CREATE TABLE inventory (
    sku          TEXT NOT NULL REFERENCES products(sku),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    on_hand      INTEGER NOT NULL CHECK (on_hand >= 0),
    reserved     INTEGER NOT NULL CHECK (reserved >= 0),
    PRIMARY KEY (sku, warehouse_id)
);

CREATE TABLE shipments (
    shipment_id             TEXT PRIMARY KEY, -- e.g. SHP-5003
    order_id                TEXT NOT NULL REFERENCES orders(order_id),
    carrier                 TEXT NOT NULL,
    tracking_number         TEXT NOT NULL,
    status                  TEXT NOT NULL
        CHECK (status IN ('IN_TRANSIT', 'DELAYED', 'DELIVERED')),
    dispatch_date           TEXT NOT NULL,
    original_estimated_date TEXT NOT NULL,
    current_estimated_date  TEXT,             -- NULL when the carrier gave no revised estimate
    delivered_date          TEXT,
    delay_reason            TEXT              -- NULL when no delay has been recorded
);

CREATE TABLE shipment_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT NOT NULL REFERENCES shipments(shipment_id),
    event_date  TEXT NOT NULL,
    location    TEXT NOT NULL,
    event_type  TEXT NOT NULL,                -- PICKED_UP, IN_TRANSIT, ARRIVED_AT_HUB, DELAY, ...
    description TEXT NOT NULL
);

-- Service alerts published by carriers (hub closures, weather, backlogs).
CREATE TABLE carrier_alerts (
    alert_id    TEXT PRIMARY KEY,             -- e.g. ALR-701
    carrier     TEXT NOT NULL,
    location    TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    alert_type  TEXT NOT NULL,                -- HUB_CLOSURE, WEATHER, BACKLOG, ...
    description TEXT NOT NULL
);

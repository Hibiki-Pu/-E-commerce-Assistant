PRAGMA foreign_keys = ON;

CREATE TABLE dataset_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    label TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (currency = 'CNY'),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL CHECK (end_date >= start_date),
    seed INTEGER NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1)
);
CREATE TABLE products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1)
);
CREATE TABLE product_costs (
    id INTEGER PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    effective_from TEXT NOT NULL CHECK (length(effective_from) = 10),
    unit_cost_cents INTEGER CHECK (unit_cost_cents IS NULL OR (typeof(unit_cost_cents) = 'integer' AND unit_cost_cents >= 0)),
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1),
    UNIQUE(product_id, effective_from)
);
CREATE TABLE order_lines (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(id),
    paid_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','cancelled','paid','shipped','completed','refunded')),
    quantity INTEGER NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity > 0),
    paid_amount_cents INTEGER NOT NULL CHECK (typeof(paid_amount_cents) = 'integer' AND paid_amount_cents >= 0),
    unit_cost_cents INTEGER CHECK (unit_cost_cents IS NULL OR (typeof(unit_cost_cents) = 'integer' AND unit_cost_cents >= 0)),
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1),
    CHECK (status IN ('pending','cancelled') OR paid_date IS NOT NULL),
    CHECK (status NOT IN ('pending','cancelled') OR (paid_date IS NULL AND paid_amount_cents = 0))
);
CREATE INDEX order_date_product ON order_lines(paid_date, product_id);
CREATE TABLE refunds (
    id TEXT PRIMARY KEY,
    order_line_id TEXT NOT NULL REFERENCES order_lines(id),
    refund_date TEXT NOT NULL CHECK (length(refund_date) = 10),
    status TEXT NOT NULL CHECK (status IN ('success','processing','failed')),
    amount_cents INTEGER NOT NULL CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1)
);
CREATE INDEX refund_date ON refunds(refund_date);
CREATE INDEX refund_line ON refunds(order_line_id);
CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1)
);

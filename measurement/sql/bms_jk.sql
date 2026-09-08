-- bms_jk table: one row per BLE poll of the JK BMS (~every 30 s)
CREATE TABLE IF NOT EXISTS bms_jk (
    id                      BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    bms_timestamp           VARCHAR(24)  DEFAULT NULL,  -- ISO from BMS read cycle (UTC)
    battery_voltage_V       FLOAT        DEFAULT NULL,
    current_A               FLOAT        DEFAULT NULL,   -- negative = discharging
    power_W                 FLOAT        DEFAULT NULL,
    soc                     TINYINT UNSIGNED DEFAULT NULL,
    capacity_remaining_Ah   FLOAT        DEFAULT NULL,
    nominal_capacity_Ah     FLOAT        DEFAULT NULL,
    soh                     TINYINT UNSIGNED DEFAULT NULL,
    cycles                  SMALLINT UNSIGNED DEFAULT NULL,
    cells_active            TINYINT UNSIGNED DEFAULT NULL,
    cell_high_V             FLOAT        DEFAULT NULL,
    cell_low_V              FLOAT        DEFAULT NULL,
    cell_delta_mV           SMALLINT     DEFAULT NULL,
    cell_avg_mV             SMALLINT     DEFAULT NULL,
    mos_temp_C              FLOAT        DEFAULT NULL,
    t1_C                    FLOAT        DEFAULT NULL,
    t2_C                    FLOAT        DEFAULT NULL,
    balance_current_A       FLOAT        DEFAULT NULL,
    balancing               TINYINT(1)   DEFAULT NULL,
    charge_mosfet           TINYINT(1)   DEFAULT NULL,
    discharge_mosfet        TINYINT(1)   DEFAULT NULL,
    errors                  VARCHAR(255) DEFAULT NULL,  -- comma-joined error list
    -- cell voltages as columns for the (up to) 16 active cells
    cell01 FLOAT DEFAULT NULL, cell02 FLOAT DEFAULT NULL,
    cell03 FLOAT DEFAULT NULL, cell04 FLOAT DEFAULT NULL,
    cell05 FLOAT DEFAULT NULL, cell06 FLOAT DEFAULT NULL,
    cell07 FLOAT DEFAULT NULL, cell08 FLOAT DEFAULT NULL,
    cell09 FLOAT DEFAULT NULL, cell10 FLOAT DEFAULT NULL,
    cell11 FLOAT DEFAULT NULL, cell12 FLOAT DEFAULT NULL,
    cell13 FLOAT DEFAULT NULL, cell14 FLOAT DEFAULT NULL,
    cell15 FLOAT DEFAULT NULL, cell16 FLOAT DEFAULT NULL,
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

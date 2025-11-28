import mysql.connector
import time
import pandas as pd
import re

class P1Storage:
    """
    Stores P1 DSMR smart-meter data (in dataframe form)
    into a MariaDB table using OBIS → column mapping.
    """

    # Mapping from DataFrame OBIS to DB column names
    OBIS_TO_DB = {
        "1-3:0:.2.8": "1_3_0_2_8",
        "0-0:1:.0.0": "0_0_1_0_0",
        "0-0:96:.1.1": "0_0_96_1_1",
        "1-0:1:.8.1": "1_0_1_8_1",
        "1-0:1:.8.2": "1_0_1_8_2",
        "1-0:2:.8.1": "1_0_2_8_1",
        "1-0:2:.8.2": "1_0_2_8_2",
        "0-0:96:.14.0": "0_0_96_14_0",
        "1-0:1:.7.0": "1_0_1_7_0",
        "1-0:2:.7.0": "1_0_2_7_0",
        "0-0:96:.7.21": "0_0_96_7_21",
        "0-0:96:.7.9": "0_0_96_7_9",
        "1-0:99:.97.0": "1_0_99_97_0",
        "1-0:32:.32.0": "1_0_32_32_0",
        "1-0:52:.32.0": "1_0_52_32_0",
        "1-0:72:.32.0": "1_0_72_32_0",
        "1-0:32:.36.0": "1_0_32_36_0",
        "1-0:52:.36.0": "1_0_52_36_0",
        "1-0:72:.36.0": "1_0_72_36_0",
        "1-0:32:.7.0": "1_0_32_7_0",
        "1-0:52:.7.0": "1_0_52_7_0",
        "1-0:72:.7.0": "1_0_72_7_0",
        "1-0:31:.7.0": "1_0_31_7_0",
        "1-0:51:.7.0": "1_0_51_7_0",
        "1-0:71:.7.0": "1_0_71_7_0",
        "1-0:21:.7.0": "1_0_21_7_0",
        "1-0:41:.7.0": "1_0_41_7_0",
        "1-0:61:.7.0": "1_0_61_7_0",
        "1-0:22:.7.0": "1_0_22_7_0",
        "1-0:42:.7.0": "1_0_42_7_0",
        "1-0:62:.7.0": "1_0_62_7_0",
        "0-1:24:.1.0": "0_1_24_1_0",
        "0-1:96:.1.0": "0_1_96_1_0",
        "0-1:24:.2.1": "0_1_24_2_1",
    }

    def __init__(self, host, user, password, database, table="p1_data"):
        self.table = table
        self.connection = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            autocommit=True
        )
        self.cursor = self.connection.cursor()

    def df_to_dict(self, df: pd.DataFrame) -> dict:
        """
        Convert dataframe to a dictionary matching DB column names.
        Unknown OBIS codes are ignored automatically.
        """
        row = {}

        for _, rec in df.iterrows():
            obis = rec["OBIS"]
            value = rec["Value"]

            if obis in self.OBIS_TO_DB:
                # Remove letters and keep numbers, dot, minus sign
                clean_value = re.sub(r"[^0-9\.-]", "", str(value))
                row[self.OBIS_TO_DB[obis]] = clean_value

        return row

    def store(self, df: pd.DataFrame):
        """
        Insert dataframe values into MariaDB.
        """

        start = time.time()

        data_dict = self.df_to_dict(df)

        # Prepare INSERT
        columns = ", ".join(data_dict.keys())
        placeholders = ", ".join(["%s"] * len(data_dict))
        sql = f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})"

        try:
            self.cursor.execute(sql, list(data_dict.values()))
        except Exception as e:
            print(f"DB Insert ERROR: {e}")
            return False

        elapsed = (time.time() - start) * 1000
        #print(f"Inserted P1 dataset in {elapsed:.1f} ms")

        return True
    
    def log_store(self,
              import_p=0.0, export_p=0.0, power_diff=0.0, pid_power=0.0,
              L1=0.0, L2=0.0, L3=0.0,
              war_power=0.0, rid_P_out=0.0, current=0.0, v_out=0.0):
        """
        Stores real-time inverter/meter status into t_logs table.
        Values equal to zero are stored as NULL.
        """

        # Build dict
        fields = {
            "import_p": import_p if import_p != 0.0 else None,
            "export_p": export_p if export_p != 0.0 else None,
            "power_diff": power_diff if power_diff != 0.0 else None,
            "pid_power": pid_power if pid_power != 0.0 else None,
            "L1": L1 if L1 != 0.0 else None,
            "L2": L2 if L2 != 0.0 else None,
            "L3": L3 if L3 != 0.0 else None,
            "war_power": war_power if war_power != 0.0 else None,
            "rid_P_out": rid_P_out if rid_P_out != 0.0 else None,
            "current": current if current != 0.0 else None,
            "v_out": v_out if v_out != 0.0 else None,
        }

        # Only keep non-None values
        row = {k: v for k, v in fields.items() if v is not None}

        if not row:
            return True  # nothing to insert

        columns = ", ".join(row.keys())
        placeholders = ", ".join(["%s"] * len(row))
        sql = f"INSERT INTO t_logs ({columns}) VALUES ({placeholders})"

        try:
            self.cursor.execute(sql, list(row.values()))
        except Exception as e:
            print(f"DB Insert ERROR (energy): {e}")
            return False

        return True


    def close(self):
        self.cursor.close()
        self.connection.close()

import mysql.connector
from mysql.connector import Error
import matplotlib.pyplot as plt

class EnergyLogger:
    """
    Connects to MariaDB and fetches data from t_logs.
    """

    VALID_COLUMNS = [
        "import_p", "export_p", "power_diff", "pid_power",
        "L1", "L2", "L3", "war_power", "rid_P_out", "current", "v_out"
    ]

    def __init__(self, host="192.168.2.26", user="admin", password="aaa", database="energy"):
        try:
            self.conn = mysql.connector.connect(
                host=host,
                user=user,
                password=password,
                database=database
            )
            self.cursor = self.conn.cursor(dictionary=True)
            print("Connected to database successfully.")
        except Error as e:
            print(f"Error connecting to database: {e}")
            self.conn = None
            self.cursor = None

    def fetch_columns(self, column_names, start_time=None, end_time=None):
        """
        Fetches multiple columns' values along with timestamps from t_logs
        and plots them on the same graph over a given time range.
        """
        if self.cursor is None:
            print("No database connection.")
            return

        # Ensure column_names is a list
        if isinstance(column_names, str):
            column_names = [column_names]

        # Validate column names
        for col in column_names:
            if col not in self.VALID_COLUMNS:
                print(f"Invalid column name: {col}")
                return

        columns_str = ", ".join(column_names)
        sql = f"SELECT created_at, {columns_str} FROM t_logs WHERE 1=1"
        params = []

        if start_time:
            sql += " AND created_at >= %s"
            params.append(start_time)
        if end_time:
            sql += " AND created_at <= %s"
            params.append(end_time)

        sql += " ORDER BY created_at ASC"

        try:
            self.cursor.execute(sql, params)
            rows = self.cursor.fetchall()
            if not rows:
                print("No data found for the given period.")
                return

            times = [row['created_at'] for row in rows]

            # Plot all columns on the same graph
            plt.figure(figsize=(12, 6))
            for col in column_names:
                values = [row[col] / 1000 if col == "war_power" and row[col] is not None else row[col] for row in rows]

                print(f"\nColumn: {col}")
                for t, v in zip(times, values):
                    print(f"{t} - {col}: {v}")

                plt.plot(times, values, label=col, linewidth=1.5)  # line plot, no dots

            plt.xlabel("Time")
            plt.ylabel("Values")
            plt.title("Energy Logger Data")
            plt.legend()
            plt.grid(True)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.show()

        except Error as e:
            print(f"Error fetching data: {e}")


    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("Connection closed.")


if __name__ == "__main__":
    logger = EnergyLogger()

    start = "2025-11-26 12:20:00"
    end = "2025-11-27 23:59:59"

    # Example: plot multiple columns on the same plot
    logger.fetch_columns(["import_p", "export_p", "power_diff", "pid_power",
        "L1", "L2", "L3", "war_power", "rid_P_out"], start_time=start, end_time=end)

    logger.close()

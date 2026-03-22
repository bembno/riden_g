import time


class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0, max_change_ratio=0.1):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint

        # max output change per step (0.1 = 10% of full range)
        self.max_change_ratio = max_change_ratio

        self.integral = 0.0
        self.last_time = None
        self.last_output = 0.0
        self.last_measured = 0.0

        # optional default voltage (used in PtoI)
        self.set_v_set_initial = 0

    def adjustPower(self, measured_value, min_output=-1.8, filter_coef=0.1, max_output=0.9):
        """
        Stable PID controller with:
        - derivative on measurement (no kick)
        - integral clamping (anti-windup)
        - rate limiting
        """

        now = time.time()
        if self.last_time is None:
            self.last_time = now
            self.last_measured = measured_value
            return 0.0
        
        dt = now - self.last_time

        #measurement filtering
        if self.last_measured is not None:
            filtered_measured_value = filter_coef * measured_value + (1 - filter_coef) * self.last_measured
        else:
            filtered_measured_value = 0.0
        # --- Error ---
        error = filtered_measured_value - self.setpoint

        # --- Integral ---
        #self.integral += error * dt
        # Only integrate if NOT saturating in same direction
        if not ((self.last_output >= max_output and error > 0) or
                (self.last_output <= min_output and error < 0)):
            self.integral += error * dt

        # --- Derivative (on measurement, prevents kick) ---
        if self.last_measured is None:
            derivative = 0.0
        else:
            derivative = -(filtered_measured_value - self.last_measured) / dt

        # --- PID output ---
        output = (
            self.kp * error +
            self.ki * self.integral +
            self.kd * derivative
        )

        # --- Clamp output ---
        output = max(min(output, max_output), min_output)

        # --- Anti-windup ---
        if self.ki != 0.0:
            max_integral = max_output / self.ki
            min_integral = min_output / self.ki
            self.integral = max(min(self.integral, max_integral), min_integral)

        # --- Rate limiting ---
        full_range = max_output - min_output
        max_change = self.max_change_ratio * full_range

        delta = output - self.last_output
        if delta > max_change:
            output = self.last_output + max_change
        elif delta < -max_change:
            output = self.last_output - max_change

        # --- Save state ---
        self.last_time = now
        self.last_output = output
        self.last_measured = filtered_measured_value

        return output

    def PtoI(self, power_kwatts, voltage=0, max_current=30.0):
        """
        Convert power (kW) to current (A)
        """

        if voltage == 0:
            voltage = self.set_v_set_initial

        if voltage == 0:
            return 0.0  # avoid division by zero

        current = abs(power_kwatts * 1000 / voltage)
        safe_current = round(min(current, max_current), 3)

        return safe_current
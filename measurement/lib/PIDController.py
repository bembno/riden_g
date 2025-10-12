import time

class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None
        self.last_output = 0.0  # for rate limiting

    def adjustPower(self, measured_value, min_output=-1.8, max_output=0.9, max_change_ratio=2.0):
        """
        Adjust power output based on measured value.

        Parameters:
            measured_value (float): Current measurement.
            min_output (float): Minimum allowed output.
            max_output (float): Maximum allowed output.
            max_change_ratio (float): Maximum allowed relative change (e.g., 2.0 = ±200%).
        """
        error = measured_value - self.setpoint
        now = time.time()
        dt = 1.0
        if self.last_time is not None:
            dt = now - self.last_time

        # --- PID core ---
        self.integral += error * dt
        derivative = (error - self.last_error) / dt if dt > 0 else 0.0
        output = self.kp * error + self.ki * self.integral + self.kd * derivative

        # --- Anti-windup ---
        if max_output is not None and self.ki != 0.0:
            if output > max_output:
                self.integral -= error * dt
                output = max_output
            elif output < min_output:
                self.integral -= error * dt
                output = min_output

        # --- Rate limiter (±max_change_ratio * previous absolute value) ---
        if self.last_time is not None:
            max_change = abs(self.last_output) * max_change_ratio
            if abs(self.last_output) < 0.05:
                # small values → allow some minimal movement
                max_change = 0.1
            upper_limit = self.last_output + max_change
            lower_limit = self.last_output - max_change
            output = max(min(output, upper_limit), lower_limit)

        # --- Clamp to min/max range ---
        output = max(min(output, max_output), min_output)

        # --- Save for next loop ---
        self.last_error = error
        self.last_time = now
        self.last_output = output

        return output

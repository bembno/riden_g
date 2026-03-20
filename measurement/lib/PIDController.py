import time

class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0,max_change_ratio=5.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.max_change_ratio=max_change_ratio
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None
        self.last_output = 0.0  # for rate limiting

    def adjustPower(self, measured_value, min_output=-1.8, max_output=0.9):
        """
        Stable PID with fixed rate limiting (10% of full range per step).
        """

        error = measured_value - self.setpoint
        now = time.time()

        dt = (now - self.last_time) if self.last_time else 1.0

        # --- PID core ---
        if min_output < self.last_output < max_output:
            self.integral += error * dt

        derivative = (error - self.last_error) / dt if dt > 0 else 0.0

        output = (
            self.kp * error +
            self.ki * self.integral +
            self.kd * derivative
        )

        # --- Clamp BEFORE rate limit (prevents windup explosion) ---
        output = max(min(output, max_output), min_output)

        # --- Anti-windup correction ---
        if self.ki != 0.0:
            if output == max_output or output == min_output:
                self.integral -= error * dt

        # --- Fixed rate limiter (10% of full range) ---
        if self.last_time is not None:
            full_range = max_output - min_output  # e.g. 2.7 kW
            max_change = 0.5 * full_range        # 10% → 0.27 kW

            upper_limit = self.last_output + max_change
            lower_limit = self.last_output - max_change

            output = max(min(output, upper_limit), lower_limit)

        # --- Save state ---
        self.last_error = error
        self.last_time = now
        self.last_output = output

        return output
    
    def PtoI(self, power_kwatts, voltage=0, max_current=30.0):
            if voltage==0:
                voltage=self.set_v_set_initial
                
            current = abs( power_kwatts * 1000 / voltage)
            safe_current = round(min(current, max_current),3)
            return safe_current

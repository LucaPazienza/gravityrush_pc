/* Motion sensors of the PC itself (handhelds such as the ROG Xbox Ally, whose built-in gamepad
 * has no gyro), for runtime_pad.c when the gamepad has none: runtime_host_motion.c. */
#pragma once

/* Starts the sensors on first use. Fills the angular velocity (rad/s) and the acceleration
 * (m/s^2, gravity read as +g upwards) on SDL's gamepad axes, with the screen and the buttons as
 * the gamepad's top face; accel may be NULL. Returns 0 without a gyro, 1 with the gyro only and 3 when accel was
 * filled too. */
int host_motion_read(float gyro[3], float accel[3]);
/* For the log: the sensor's name and report interval, or NULL without one. */
const char *host_motion_describe(void);

import time

try:
    from gpiozero import PWMOutputDevice, DigitalOutputDevice
except ImportError:
    print("gpiozero is required on Raspberry Pi.")
    raise


class PiL298NMotorController:

    def __init__(self):

        self.ena = PWMOutputDevice(
            12,
            frequency=1000
        )

        self.in1 = DigitalOutputDevice(5)
        self.in2 = DigitalOutputDevice(6)

        self.enb = PWMOutputDevice(
            13,
            frequency=1000
        )

        self.in3 = DigitalOutputDevice(16)
        self.in4 = DigitalOutputDevice(20)

        self.stop()


    def left_motor(
        self,
        direction,
        speed
    ):

        speed = max(
            0.0,
            min(1.0, speed)
        )

        if direction == "FORWARD":

            self.in1.on()
            self.in2.off()

        elif direction == "BACKWARD":

            self.in1.off()
            self.in2.on()

        else:

            self.in1.off()
            self.in2.off()

            speed = 0.0

        self.ena.value = speed


    def right_motor(
        self,
        direction,
        speed
    ):

        speed = max(
            0.0,
            min(1.0, speed)
        )

        if direction == "FORWARD":

            self.in3.on()
            self.in4.off()

        elif direction == "BACKWARD":

            self.in3.off()
            self.in4.on()

        else:

            self.in3.off()
            self.in4.off()

            speed = 0.0

        self.enb.value = speed


    def execute(
        self,
        left_direction,
        left_speed,
        right_direction,
        right_speed
    ):

        self.left_motor(
            left_direction,
            left_speed / 100.0
        )

        self.right_motor(
            right_direction,
            right_speed / 100.0
        )


    def stop(self):

        self.ena.value = 0
        self.enb.value = 0

        self.in1.off()
        self.in2.off()

        self.in3.off()
        self.in4.off()


    def cleanup(self):

        self.stop()

        self.ena.close()
        self.enb.close()

        self.in1.close()
        self.in2.close()

        self.in3.close()
        self.in4.close()


if __name__ == "__main__":

    motor = PiL298NMotorController()

    print("L298N Motor Controller")
    print("----------------------")

    try:

        print("STOP")
        motor.stop()

        time.sleep(2)

        print("FORWARD")
        motor.execute(
            "FORWARD",
            50,
            "FORWARD",
            50
        )

        time.sleep(3)

        print("STOP")
        motor.stop()

        time.sleep(2)

        print("BACKWARD")
        motor.execute(
            "BACKWARD",
            50,
            "BACKWARD",
            50
        )

        time.sleep(3)

        print("STOP")
        motor.stop()

        time.sleep(2)

        print("TURN LEFT")
        motor.execute(
            "FORWARD",
            30,
            "FORWARD",
            60
        )

        time.sleep(3)

        print("STOP")
        motor.stop()

        time.sleep(2)

        print("TURN RIGHT")
        motor.execute(
            "FORWARD",
            60,
            "FORWARD",
            30
        )

        time.sleep(3)

        print("STOP")
        motor.stop()

        print()
        print("Motor test completed.")

    except KeyboardInterrupt:

        print()
        print("Emergency stop.")

    finally:

        motor.cleanup()
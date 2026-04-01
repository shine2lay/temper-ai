"""Tests for Calculator tool."""

import math

from temper_ai.tools.calculator import Calculator


class TestCalculator:
    def setup_method(self):
        self.calc = Calculator()

    def test_basic_arithmetic(self):
        r = self.calc.execute(expression="2 + 3")
        assert r.success is True
        assert r.result == "5"

    def test_multiplication(self):
        r = self.calc.execute(expression="7 * 8")
        assert r.result == "56"

    def test_division(self):
        r = self.calc.execute(expression="10 / 3")
        assert float(r.result) == 10 / 3

    def test_floor_division(self):
        r = self.calc.execute(expression="10 // 3")
        assert r.result == "3"

    def test_modulo(self):
        r = self.calc.execute(expression="10 % 3")
        assert r.result == "1"

    def test_power(self):
        r = self.calc.execute(expression="2 ** 10")
        assert r.result == "1024"

    def test_negative(self):
        r = self.calc.execute(expression="-5 + 3")
        assert r.result == "-2"

    def test_parentheses(self):
        r = self.calc.execute(expression="(2 + 3) * 4")
        assert r.result == "20"

    def test_nested_expression(self):
        r = self.calc.execute(expression="((1 + 2) * (3 + 4))")
        assert r.result == "21"

    def test_sqrt(self):
        r = self.calc.execute(expression="sqrt(16)")
        assert r.result == "4.0"

    def test_sin_pi(self):
        r = self.calc.execute(expression="sin(pi / 2)")
        assert float(r.result) == 1.0

    def test_cos(self):
        r = self.calc.execute(expression="cos(0)")
        assert float(r.result) == 1.0

    def test_log(self):
        r = self.calc.execute(expression="log(e)")
        assert abs(float(r.result) - 1.0) < 1e-10

    def test_abs(self):
        r = self.calc.execute(expression="abs(-42)")
        assert r.result == "42"

    def test_round(self):
        r = self.calc.execute(expression="round(3.7)")
        assert r.result == "4"

    def test_min_max(self):
        r = self.calc.execute(expression="min(3, 7)")
        assert r.result == "3"
        r = self.calc.execute(expression="max(3, 7)")
        assert r.result == "7"

    def test_pi_constant(self):
        r = self.calc.execute(expression="pi")
        assert abs(float(r.result) - math.pi) < 1e-10

    def test_e_constant(self):
        r = self.calc.execute(expression="e")
        assert abs(float(r.result) - math.e) < 1e-10

    def test_complex_expression(self):
        r = self.calc.execute(expression="sqrt(3**2 + 4**2)")
        assert float(r.result) == 5.0

    # -- Error cases --

    def test_empty_expression(self):
        r = self.calc.execute(expression="")
        assert r.success is False

    def test_division_by_zero(self):
        r = self.calc.execute(expression="1 / 0")
        assert r.success is False

    def test_unknown_function(self):
        r = self.calc.execute(expression="eval('os.system(\"ls\")')")
        assert r.success is False

    def test_unknown_variable(self):
        r = self.calc.execute(expression="x + 1")
        assert r.success is False
        assert "Unknown variable" in r.error

    def test_huge_exponent_blocked(self):
        r = self.calc.execute(expression="2 ** 10000")
        assert r.success is False
        assert "too large" in r.error.lower()

    def test_no_code_execution(self):
        r = self.calc.execute(expression="__import__('os').system('ls')")
        assert r.success is False

    def test_modifies_state_false(self):
        assert self.calc.modifies_state is False

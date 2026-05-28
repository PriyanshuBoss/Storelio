from decimal import Decimal
class NumberUtilities:
    
    @staticmethod
    def convert_string_to_number(string):
        number = 0
        
        try:
            number = int(string)
        except Exception as e:
            pass

        return number

    @staticmethod
    def convert_string_to_float(string):
        number = 0.0
        
        try:
            number = float(string)
        except Exception as e:
            pass

        return number
    
    @staticmethod
    def convert_string_to_decimal(string):
        number = Decimal(0.0)
        
        try:
            number = Decimal(string)
        except Exception as e:
            pass

        return number

    @staticmethod
    def convert_integer_to_hexadecimal(num):
        num = int(num)

        try:
            hexa = hex(num)
        except Exception as e:
            return
            
        return hexa

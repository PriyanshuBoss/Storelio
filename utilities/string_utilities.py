import uuid
class StringUtilities:
    
    @staticmethod
    def convert_number_to_string(number):
        string = ""
        
        try:
            string = str(number)
        except Exception as e:
            pass

        return string

    @staticmethod
    def convert_object_to_string(value):
        string = ""
        
        try:
            string = str(value)
        except Exception as e:
            pass

        return string

    @staticmethod
    def convert_list_of_object_to_string(value_list):
        value_list_string = []

        for value in value_list:
            
            string = ""
        
            try:
                string = str(value)

            except Exception as e:
                pass
            
            value_list_string.append(string)
        
        return value_list_string
        

    @staticmethod
    def convert_object_to_line_seperated_string(obj):
        string = ''
        try:
            values = []
            for key,value in obj.items():
                values.append(f"{key}: {value}")
            
            string = '\n\n'.join(values)

        except Exception as e:
            pass

        return string

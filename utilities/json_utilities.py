import json

class JsonUtilities:

    @staticmethod
    def loads(data):
        json_data = {}
        try:
            json_data = json.loads(data)
        except Exception as e:
            pass
        return json_data


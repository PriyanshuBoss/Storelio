from django.db import connection

class RawSQLUtilities():

    @staticmethod
    def run_raw_sql_quries(query):

        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            query_result = [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]
            
            return query_result

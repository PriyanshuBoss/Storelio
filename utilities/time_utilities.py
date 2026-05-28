import time
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from datetime import date
from .number_utilities import NumberUtilities


class TimeUtilities:

    @staticmethod
    def current_time_in_milliseconds() -> int:
        return int((time.time() * 1000))

    @staticmethod
    def convert_seconds_to_milliseconds(epoch_time_sec) -> int:
        return int(epoch_time_sec * 1000)

    @staticmethod
    def parse_date(date_obj=None, date_format="%d-%m-%Y"):
        return date_obj.strftime(date_format)

    def parse_date_tz(hour: int):
        d = datetime.utcnow()+timedelta(hours = 5.5+hour)
        date_string = ""
        date_string = date_string+str(f"{d:%Y}")+"-"+str(f"{d:%m}")+"-"+str(f"{d:%d}")+"T"+str(f"{d:%H}")+":"+str(f"{d:%M}")+":"+str(f"{d:%S}")+"Z"
        return  date_string

    def get_current_date_time():
        return timezone.now()
    
    def get_current_date_time_utc():
        return datetime.utcnow()
        
    @staticmethod
    def get_time_with_delta(time_delta=600):
        return timezone.now() + timedelta(seconds=time_delta)

    @staticmethod
    def get_datetime_between_duration(day=1, limit=20):
        """returns the dates between particular duration from day"""
        
        if day == 1:
            end_date = timezone.now()
            start_date = end_date - timedelta(days=limit, hours=end_date.hour, minutes=end_date.minute, seconds=end_date.second)
        else:
            today_date = timezone.now() - timedelta(days=1)
            end_date = today_date - timedelta(days=limit*(day-1), hours=today_date.hour, minutes=today_date.minute, seconds= today_date.second) + timedelta(hours=23, minutes=59, seconds=59)
            start_date = end_date - timedelta(days=limit, hours=end_date.hour, minutes=end_date.minute, seconds=end_date.second)

        return start_date, end_date

    @staticmethod
    def add_time_in_timestamp(start_time, days=0, minutes=0, seconds=0,hours=0):
        return start_time + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    @staticmethod
    def subtract_time_from_timestamp(start_time, days=0, hours=0, minutes=0, seconds=0):
        return start_time - timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    @staticmethod
    def get_current_date(parse = True):
        if parse:
            return TimeUtilities.parse_date(date.today())
        else:
            return (date.today())

    @staticmethod
    def get_current_time():
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        return current_time
        
    def now_local(self, only_date=False):
        """
        In this method takes only date is true or false. If true means return the date (2021-03-15).
        If false means return the date with time (2021-03-15 13:09:08).
        :param only_date: true / false
        :return: date (2021-03-15) and date with time (2021-03-15 13:09:08)
        """
        if only_date:
            return (timezone.localtime(timezone.now())).date()
        else:
            return timezone.localtime(timezone.now())
    
    def get_last_hour_date_time(self):
        """
        :return: last hour Date and time (YYYY-MM-DD HH:MM:SS): 2021-03-15 12:00:00
        """
        return timezone.now() - timedelta(hours = 1)

    def get_today_start(self):
        """
        :return: Start Date (YYYY-MM-DD HH:MM:SS): 2021-03-1 00:00:00
        """
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    def get_today_end(self):
        """
        :return: End Date (YYYY-MM-DD HH:MM:SS): 2021-03-15 23:59:59
        """
        tomorrow = self.get_today_start() + timedelta(days=1)
        return tomorrow - timedelta(microseconds=1)

    def get_current_week_start(self):
        """
        :return: Start Date of week (YYYY-MM-DD HH:MM:SS): 2021-03-15 23:59:59
        """

        return self.get_today_start() - timedelta(days=self.get_today_start().weekday())

    
    def get_yesterdays_date(self):
        """
        :return will return yesterday
        """
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    
    def get_current_month_start(self):
        """
        It will not take any params. It will returns month start date.
        :return: Month Start Date (YYYY-MM-DD HH:MM:SS): 2021-03-1 00:00:00
        """
        return self.get_today_start().replace(day=1)

    def get_prev_month_boundaries(self):
        """
        Will return the previous month start date (2021-02-1 00:00:00) and previous month end date (2021-02-29 23:59:59).
        :return: (prev_month_start_date, prev_month_end_date)
        """
        prev_month_end_date = self.get_current_month_start() - timedelta(microseconds=1)
        if prev_month_end_date:
            prev_month_start_date = prev_month_end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return prev_month_start_date, prev_month_end_date
    
    def get_prev_week_boundaries(self):
        """
        Will return the previous week start date (2021-02-1 00:00:00) and previous week end date (2021-01-25 23:59:59).
        :return: (prev_week_start_date, prev_week_end_date)
        """
        prev_week_end_date = self.get_current_week_start() - timedelta(microseconds=1)
        if prev_week_end_date:
            prev_week_start_date = prev_week_end_date - timedelta(days=6)
        return prev_week_start_date, prev_week_end_date

    @staticmethod
    def validate_date(date_text, date_format="%Y-%m-%d"):
        
        try:
            datetime.strptime(date_text, date_format)
            return True
        
        except ValueError:
            return False
    
    @staticmethod
    def convert_datetime_to_string(date_time , date_format='%Y-%m-%d %H:%M:%S'):
        
        try:
            new_date_time = date_time.strftime(date_format)
            return new_date_time
        except Exception as e:
            return ""

    @staticmethod
    def get_n_days_before_date(days):
        """
        Will return the date seven days before .
        :return : (seven_days_before_date)
        """
        todays_date = date.today()
        seven_days_before_date = todays_date - timedelta(days=days)
        return seven_days_before_date
    
    @staticmethod
    def convert_string_to_datetime(string,index=0):

        strptime_formats = ['%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S.%f','%Y-%m-%d %H:%M:%S.%f','%Y-%m-%dT%H:%M:%S','%Y-%m-%dT%H:%M:%S.%f%z','%Y-%m-%d']

        if index>=len(strptime_formats):
            return None

        try:
            date_time_format = datetime.strptime(string, strptime_formats[index]).replace(tzinfo=None)
            return date_time_format

        except Exception:
            return TimeUtilities.convert_string_to_datetime(string,index+1)
            
    @staticmethod
    def convert_date_to_datetime(date):
        return datetime(
                            year=date.year, 
                            month=date.month,
                            day=date.day,
                        )

    @staticmethod
    def convert_epoch_to_datetime(epoch):
        try:
            date_time = datetime.datetime.fromtimestamp(epoch) 
            return date_time
        except Exception:
            return epoch
        
    @staticmethod
    def get_current_month():
        current_date = datetime.now()
        current_month = current_date.month
        return current_month
    
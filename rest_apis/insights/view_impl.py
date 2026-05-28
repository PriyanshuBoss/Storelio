from django.http import HttpResponse, JsonResponse
from saleor.utilities.json_utilities import JsonUtilities
from saleor.utilities.time_utilities import TimeUtilities
from .insights_helper import page_load_time_format_new_data, page_load_time_merge_current_data, page_load_time_save_new_data, page_load_time_get_data

def page_load_time(request):

    if request.method == 'POST':
        try:
            new_data = JsonUtilities.loads(request.body)
            if not new_data:
                return HttpResponse(status=400)
            
            new_data = page_load_time_format_new_data(new_data)
            new_data = page_load_time_merge_current_data(new_data)

            saved = page_load_time_save_new_data(new_data)
            if not saved:
                return HttpResponse(status=500)

            return HttpResponse(status=200)
            
        except Exception as e:
            return HttpResponse(status=400)

    elif request.method == 'GET':
        date        = request.GET.get('date')
        start_date  = request.GET.get('start_date')
        end_date    = request.GET.get('end_date')

        if not date and not start_date and not end_date:
            date = TimeUtilities.get_current_date()
        if date:
            start_date = date
            end_date = date

        if start_date and end_date:
            data = page_load_time_get_data(start_date, end_date)
            return JsonResponse({'data': data})
        
        return HttpResponse(status=400)

    else:
        return HttpResponse(status=405)


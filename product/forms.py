import csv
import re
from io import BytesIO, StringIO
from re import escape

import base64
from django.utils.text import slugify
from django import forms
from django.conf import settings
from django.core.validators import FileExtensionValidator
import os
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image
from saleor.brand.models import Brand
from saleor.product.models import Category,ProductImage
from saleor.warehouse.models import Warehouse


class BulkUploadForm(forms.Form):

    brand = forms.ModelChoiceField(queryset=Brand.objects.all(), required=True)

    csv_file = forms.FileField(
        label='Select a csv file',
        help_text='Upload a file having all the allowed columns and with data in all rows for madatory columns.',
        validators=[FileExtensionValidator(allowed_extensions=['csv'])], required=True
    )

    def validate_column_names(self, fieldnames):
        invalid_column_names = set(fieldnames).difference(set(settings.PRODUCTS_CSV_UPLOAD['CSV_COLUMNS']))
        return invalid_column_names

    def clean_csv_file(self):
        reader = csv.DictReader(StringIO(self.cleaned_data['csv_file'].read().decode('utf-8')))

        self.cleaned_data['csv_file'].seek(0)
        invalid_column_names = self.validate_column_names([key.strip().lower().replace('*', '').replace("_", " ") for key in reader.fieldnames])
        
        if not set(settings.PRODUCTS_CSV_UPLOAD['MANDATORY_CSV_COLUMNS']).issubset([key.strip().lower().replace('*', '').replace("_", " ") for key in reader.fieldnames]):
            raise forms.ValidationError('Add all mandatory columns in csv')

        if invalid_column_names:
            raise forms.ValidationError('Invalid column names : {}, \
                You can use column names only from : Allowed columns'.format(invalid_column_names))
        return self.cleaned_data['csv_file']

    def check_if_zaamo_master_warehouse(self):
        try:
            warehouse = Warehouse.objects.get(slug='zaamo-master-warehouse')
        except:
            warehouse = None
        return warehouse

    def clean(self):
        if not self.check_if_zaamo_master_warehouse():
            raise forms.ValidationError('Zaamo master warehouse is not created.')
        if 'csv_file' in self.cleaned_data:
            categories = Category.objects.only("slug").values_list("slug", flat=True)
            if self.cleaned_data['brand'].brand_source not in ("manual", "staff","unicommerce"):
                raise forms.ValidationError('File can not be uploaded as brand_source is not manual or staff')
            validation_result = CsvFile.validate_file(self.cleaned_data['csv_file'], self.cleaned_data['brand'].brand_name, categories)
            if validation_result['errors']:
                raise forms.ValidationError('{}'.format(validation_result['errors']))
        super().clean()



    

class CsvFile(forms.Form):

    validate_fields = settings.PRODUCTS_CSV_UPLOAD['CSV_COLUMNS']

    def __init__(self, *args, **kwargs):
        data = {}
        for key, value in kwargs["data"].items():

            if key.strip().lower().replace('*', '').replace("_", " ") in self.validate_fields and isinstance(value, str):
                key = key.strip().lower().replace('*', '').replace(" ", "_")
                data[key] = value.strip()
            else:
                continue
        kwargs["data"] = data

        super(self.__class__, self).__init__(*args, **kwargs)


    product_name = forms.CharField(max_length=100, required=False)
    brand_id = forms.CharField(max_length=100, required=True)
    sku = forms.CharField(max_length=100, required=True)
    pid = forms.CharField(max_length=100, required=True)
    size = forms.CharField(max_length=100, required=True)
    quantity = forms.CharField(max_length=100, required=True)
    mrp = forms.CharField(max_length=100, required=True)
    search_image_url = forms.CharField(max_length=300, required=True)
    selling_price = forms.CharField(max_length= 300, required=False)
    category = forms.CharField(max_length=300, required=True)
    sub_category = forms.CharField(max_length=100, required=True)
    front_image_url = forms.CharField(max_length=300, required=False)
    back_image_url = forms.CharField(max_length=300, required=False)
    right_image_url = forms.CharField(max_length=300, required=False)
    discription = forms.CharField(max_length=100, required=False)
    color = forms.CharField(max_length=100, required=False)
    meterial = forms.CharField(max_length=100, required=False)
    hsn = forms.CharField(max_length=100, required=False)
    product_link_of_the_website = forms.CharField(max_length=200, required=False)


    def clean_size(self):
        size = self.cleaned_data["size"]

        if size not in settings.SIZE_LIST:
            raise forms.ValidationError('Enter correct size, You can only add size from {}, entered size is {}'.format(str(settings.SIZE_LIST), size))
        return size

    def clean_mrp(self):
        mrp = self.cleaned_data["mrp"].replace(',', '')

        try:
            float(mrp)
        except:
            raise forms.ValidationError('Enter correct MRP, Entered MRP is having some special\
                 character which can not be converted into numbers') 
        return mrp
    
    def clean_category(self):
        category = self.cleaned_data["category"]
        if not slugify(category) in self.categories:
            raise forms.ValidationError('Entered Catagory ({}) is not available in zaamo database'.format(category))
        
        return category


    def clean_sub_category(self):
        sub_category = self.cleaned_data["sub_category"]
        if not slugify(sub_category) in self.categories:
            raise forms.ValidationError('Entered Sub category ({}) is not available in zaamo database'.format(sub_category))
        
        return sub_category

    def clean_selling_price(self):
        selling_price = self.cleaned_data["selling_price"].replace(',', '')

        try:
            float(selling_price)
        except:
            raise forms.ValidationError('Enter correct selling price, entered selling price is having some special\
                 character which can not be converted into numbers')
        return selling_price
    
    def clean_brand_id(self):
        
        brand_id = self.cleaned_data["brand_id"]
        
        if brand_id==self.brand:
            return brand_id
        else:
            raise forms.ValidationError('Enter correct brand Id: {}'.format(brand_id))


    @classmethod
    def validate_file(cls, file, brand, categories):
        reader = csv.DictReader(StringIO(file.read().decode('utf-8')))
        
        result = {}
        error_data = []
        correct = 0
        wrong = 0
       
        for row in reader:
            error = {}
            data = cls(data=row)

            setattr(data, 'brand', brand)
            setattr(data, 'categories', categories)

            if data.is_valid():
                correct += 1
            else:
                wrong += 1
                error[data.data["sku"]] = data.errors
                error_data.append(error)
        result["errors"] = error_data
        result["Correct_count"] = correct
        result["Incorrect_count"] = wrong
        file.seek(0)
        return result
    

    
class ImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = '__all__'
    
    def save(self, commit=False):
        
        instance = super().save(commit=False)
        product_id=instance.product_id
        
        from saleor.product.tasks import save_image_with_celery

        image_data = instance.image.read()
        image_bytes = base64.b64encode(image_data).decode('utf-8')
        save_image_with_celery.delay(image_bytes,product_id)
                
        return instance

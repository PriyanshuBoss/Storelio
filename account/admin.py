import json
from django.contrib import admin
from django.forms import ValidationError, formset_factory
import graphene
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib.auth import get_user_model
from django.utils.translation import gettext, gettext_lazy as _
from django.contrib.auth.admin import UserAdmin as DjUserAdmin
from saleor.account.forms import CreateUserForm
from saleor.account.models import Address, Influencer ,InfluencerBankAccount, InfluencerUpiId,User
from saleor.plugins.manager import PluginsManager
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf.urls import url
from django.template.response import TemplateResponse


@admin.register(get_user_model())
class UserAdmin(DjUserAdmin):
    ordering = ('mobile_no',)
    change_list_template = "account/change_list.html"
    fieldsets = (
        (None, {'fields': ('password', "jwt_token_key")}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email', "mobile_no", "avatar", "note","user_name")}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions',),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
        (_('Address'), {'fields': ('default_shipping_address', 'default_billing_address')}),
    )
    list_display = ('mobile_no', 'first_name', 'last_name', 'is_active', "date_joined")
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('mobile_no', )
    readonly_fields = ("jwt_token_key", "addresses", "date_joined")
    raw_id_fields = ("default_shipping_address", "default_billing_address")

    def has_add_permission(self, request, obj=None):
            return False
    
    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get('user_name'):
            
            if User.objects.filter(user_name=form.cleaned_data['user_name']).exclude(id=obj.id).exists():
                
                raise ValidationError(
                    'The username must be unique for the User model.'
                )
            
        super().save_model(request, obj, form, change)
    
    def user_create_mutation(self,mobile):
        from saleor.graphql.api import schema
        try:
            try:
                params = {
                "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None,'META':{'HTTP_X_PLATFORM_CODE':'IH'}}
                schema_context = graphene.types.Context(**params)
            except Exception as e:
                print(e)

            query = """
                        mutation{
                        userRegister(input: {mobileNo: "%s",isActive:true}) {
                            user {
                            id
                            mobileNo
                            __typename
                            }
                            accountErrors {
                            message
                            __typename
                            }
                            __typename
                        }
                        }
                    """ % (mobile)
            response = schema.execute(query,context_value=schema_context)

            user = response.data["userRegister"]["user"]
            if not user:
                raise ValidationError(f"Error while creating user : {response}")
            return user
            
        except Exception as e:
            raise ValidationError(f"Error while creating user : {e}")

    def create_user(self,request):
        opts = self.model._meta
        app_label = opts.app_label
        formset = formset_factory(CreateUserForm)

        if request.method == 'POST':

            formset = formset_factory(CreateUserForm)(request.POST)

            if formset.is_valid():

                if 'mobile_no' in formset.forms[0].cleaned_data:
                    mobile_no = formset.forms[0].cleaned_data['mobile_no']
                    user_name = formset.forms[0].cleaned_data['user_name']
                    if not mobile_no and not user_name:
                        raise ValidationError(f"Wrong inputs")

                    user = User.objects.filter(mobile_no=mobile_no).first()
                    if not user:
                        user_details = self.user_create_mutation(mobile_no)
                        user_details['user_name']=user_name
                        self.message_user(
                        request, f"User created with details :: {user_details}"
                        )
                        user = User.objects.get(mobile_no=mobile_no)

                    if user_name:
                        if User.objects.filter(user_name=user_name).exclude(id=user.id).exists():
                
                            raise ValidationError(
                                'The username must be unique for the User model.'
                            )    
                        user.user_name = user_name
                        user.save()
                        
                    request.user = user
                    self.set_store(request,user)

        
        _dict = {
            'add': True,
            'change': False,
            'has_editable_inline_admin_formsets': False,
            'has_add_permission': True,
            "has_change_permission": True, 
            "has_view_permission": True,
            'has_file_field': True,
            "has_delete_permission": False, 
            'opts': opts,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'app_label': app_label,
            'show_save_and_add_another': False,
            'show_save_and_continue': False,
            'media': '',
            'title': 'Create User'
        }
        context = dict(
           # Include common variables for rendering the admin template.
           self.admin_site.each_context(request),
           # Anything else you want in the context...
           form=formset,
           opts= opts,
           app_label=app_label
        )
        context.update(_dict)

        return TemplateResponse(request, "account/create_user.html", context)
    
    def get_urls(self):
        urls = super(UserAdmin, self).get_urls()
        custom_page_urls = [
                url(r"^create_user/", login_required(self.create_user), name="create_user")
                ]
        
        return custom_page_urls + urls
    
    def set_store(self, request, obj):
        from saleor.plugins.manager import PluginsManager
        from saleor.graphql.api import schema
        
        
        params = {"user": request.user,
        "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None}
        schema_context = graphene.types.Context(**params)

        if not obj.user_name:
            self.message_user(
                request, "Error Occured while Influencer Creation for {} ::: No User Name found for this user.".format(obj.mobile_no),level=40
            )
            return HttpResponseRedirect(".")

        influencer_filter = Influencer.objects.filter(user = obj)

        if influencer_filter:
            self.message_user(
                request, "Influencer account for user {} already exists. Try Activating it from influencer dashboard".format(obj.mobile_no),level=40
            )
            return HttpResponseRedirect(".")

        if obj.store_members.all():
            self.message_user(
                request, "Store for user {} already exists.".format(obj.mobile_no),level=40
            )
            return HttpResponseRedirect(".")

        query = """
            mutation{
                influencerManualAccountVerification(
                    mobileNo: "%s"
                    instagramUsername: "%s"
                ){
                    user{
                    id
                    influencer{
                        name
                    }
                    }
                }
                }
        """ %  (obj.mobile_no,obj.user_name)

        response = schema.execute(query, variables={},
                                context_value=schema_context)
        if response.data:
            
            influencer_created = Influencer.objects.filter(user = obj).first()
            query = """
                mutation{
                    activateAccount(input:{
                        mobileNo: "%s"
                        name: "%s"
                        instagramUserId: "%s"
                        instagramUsername: "%s"
                        imageUrl: "%s"
                    }){
                        user{
                        id
                        influencer{
                            name
                        }
                        }
                    }
                    }
            """ %  (obj.mobile_no, influencer_created.name, influencer_created.instagram_user_id, 
            influencer_created.instagram_username, influencer_created.image_url)

            response = schema.execute(query, variables={},
                                context_value=schema_context)
            if response.data:
                self.message_user(
                    request, "Store Activated for {}".format(obj.mobile_no)
                )
            else:
                self.message_user(
                    request, "Error Occured while Store Activation for {} ::: error({})".format(obj.mobile_no, response.to_dict()),level=40
                )

        else:
                self.message_user(
                request, "Error Occured while Influencer Activation for {} ::: error({})".format(obj.mobile_no, response.to_dict()),level=40
            )
        

class InfluencerBankAccountAdmin(admin.TabularInline):
    model = InfluencerBankAccount
    extra=0

class InfluencerUpiIdAdmin(admin.TabularInline):
    model = InfluencerUpiId
    extra=0


@admin.register(Influencer)
class InfluencerAdmin(admin.ModelAdmin):
    change_form_template= 'account/change_form.html'
    list_display = ('user', 'instagram_username', 'is_active', "created_at")
    list_filter = ('ig_status', 'is_verified')
    search_fields = ('user__mobile_no', 'instagram_username')
    readonly_fields = ("created_at","state")
    raw_id_fields = ('user',)
    inlines=[InfluencerBankAccountAdmin, InfluencerUpiIdAdmin]
    def is_active(self, obj):
        return obj.is_active()

    def response_change(self, request, obj):
        """
        we will call the service for corresponding button.
        """

        # "Activate Account" Button
        if "_activate_account" in request.POST:
            from saleor.plugins.manager import PluginsManager
            from saleor.graphql.api import schema
            
            params = {"user": request.user,
            "plugins": PluginsManager(plugins=settings.PLUGINS), 'app': None}
            schema_context = graphene.types.Context(**params)

            query = """
                mutation{
                    activateAccount(input:{
                        mobileNo: "%s"
                        name: "%s"
                        instagramUserId: "%s"
                        instagramUsername: "%s"
                        imageUrl: "%s"
                    }){
                        user{
                        id
                        influencer{
                            name
                        }
                        }
                    }
                    }
            """ %  (obj.user.mobile_no, obj.name, obj.instagram_user_id, 
            obj.instagram_username, obj.image_url)

            response = schema.execute(query, variables={},
                                  context_value=schema_context)
            if response.data:
                self.message_user(
                    request, "Account Activated for {}".format(obj.user.mobile_no)
                )
            else:
                 self.message_user(
                    request, "Error Occured while Account Activation for {} ::: error({})".format(obj.user.mobile_no, response.to_dict(),level=40)
                )

            return HttpResponseRedirect(".")
            
        return super().response_change(request, obj)

    

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'company_name', 'city', 'postal_code', 'country','email')
    list_filter = ('country_area', 'postal_code', 'city')

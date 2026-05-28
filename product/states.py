
class ProductTagSourceEnum:
    NAME = 'name'
    BRANDTAG = 'brandtag'
    DESCRIPTION = 'description'
    MANUAL = 'manual'

    CHOICES = [
        (MANUAL, 'manual'),
        (NAME, 'name'),
        (BRANDTAG, 'brandtag'),
        (DESCRIPTION, 'description'),
    ]

class ProductGroupingEnum:
    TAGGED_COLLECTION = 'tagged_collection'

    CHOICES = [
        (TAGGED_COLLECTION, 'tagged_collection'),
    ]


class CollectionTypeEnum:
    ZAAMO_CURATION = 'zaamo_curation'
    BRAND_CURATION = 'brand_curation'

    CHOICES = [
        (ZAAMO_CURATION, 'zaamo_curation'),
        (BRAND_CURATION, 'brand_curation'),
    ]

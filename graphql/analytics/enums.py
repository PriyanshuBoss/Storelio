import graphene

class SortDirectionEnum(graphene.Enum):
    ASC = True
    DESC = False

    @property
    def description(self):
        # Disable all the no-member violations in this function
        # pylint: disable=no-member
        if self == SortDirectionEnum.ASC:
            return "Specifies an ascending sort order."
        if self == SortDirectionEnum.DESC:
            return "Specifies a descending sort order."
        raise ValueError("Unsupported enum value: %s" % self.value)


class BrandOrderStatus:
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    
    CHOICES = [
        (ON_TIME, "ON_TIME"),
        (DELAYED, "DELAYED")
    ]

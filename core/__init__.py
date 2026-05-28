class JobStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    DELETED = "deleted"

    CHOICES = [
        (PENDING, "Pending"),
        (SUCCESS, "Success"),
        (FAILED, "Failed"),
        (DELETED, "Deleted"),
    ]

class ModeofPayment:
    UPI = "upi"
    NEFT_OR_IMPS = "neft/imps"

    CHOICES = [
        (UPI,"Upi"),
        (NEFT_OR_IMPS,"Neft/Imps")
    ]

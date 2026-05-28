class InfluencerState:
    NOT_VERIFIED = 0
    VERIFIED = 1

class RegisterUserType:
    USER = "user"
    BRAND = "brand"
    INFLUENCER = "influencer"
    CHOICES = [
        (USER, "user"),
        (BRAND, "brand"),
        (INFLUENCER, "influencer"),
    ]

class InfluencerStatus:
    HOLD = "hold"
    REQUEST_RECEIVED = "request_received"
    IN_PROGRESS = "in progress"
    REJECTED = "rejected"
    ONBOARDED = "onboarded"
    CHOICES = [
        (HOLD, "hold"),
        (REQUEST_RECEIVED, "request_received"),
        (IN_PROGRESS, "in progress"),
        (REJECTED, "rejected"),
        (ONBOARDED, "onboarded"),
    ]

class UserMediaType:
    IMAGE = 'IMAGE'
    AUDIO = 'AUDIO'
    VIDEO = 'VIDEO'
    
    CHOICES = [
        (IMAGE, "IMAGE"),
        (AUDIO, "AUDIO"),
        (VIDEO, "VIDEO")
    ]

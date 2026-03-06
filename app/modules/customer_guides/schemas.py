from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class GuideCreate(BaseModel):
    title:      str
    content_md: str
    category:   Optional[str] = None
    tags:       List[str]     = []
    is_public:  bool          = False


class GuideUpdate(BaseModel):
    title:      Optional[str]       = None
    content_md: Optional[str]       = None
    category:   Optional[str]       = None
    tags:       Optional[List[str]] = None
    is_public:  Optional[bool]      = None


class GuideOut(BaseModel):
    id:         int
    title:      str
    content_md: str
    category:   Optional[str]
    tags:       List[str]
    is_public:  bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class FeedbackIn(BaseModel):
    helpful:  bool
    comment:  Optional[str] = None
    client_id: str


class SendGuideIn(BaseModel):
    client_id: str

"""
API URL Configuration
=====================

Mount at /api/ in the project urls.py.

Endpoints
---------
POST /api/auth/token/          — obtain auth token
GET  /api/schema/              — raw OpenAPI 3 schema (YAML)
GET  /api/docs/                — Swagger UI
GET  /api/redoc/               — ReDoc UI
GET  /api/clients/             — paginated client list
GET  /api/clients/{id}/        — client detail
GET  /api/loans/               — paginated loan list
GET  /api/loans/{id}/          — loan detail
GET  /api/savings/             — paginated savings account list
GET  /api/savings/{id}/        — savings account detail
GET  /api/reports/portfolio/   — portfolio metrics snapshot
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from .views import (
    ObtainTokenView,
    ClientViewSet,
    LoanViewSet,
    SavingsAccountViewSet,
    PortfolioReportView,
)

router = DefaultRouter()
router.register(r'clients', ClientViewSet, basename='api-client')
router.register(r'loans',   LoanViewSet,   basename='api-loan')
router.register(r'savings', SavingsAccountViewSet, basename='api-savings')

urlpatterns = [
    # Token auth
    path('auth/token/', ObtainTokenView.as_view(), name='api-token-auth'),

    # OpenAPI schema + docs
    path('schema/',     SpectacularAPIView.as_view(),           name='api-schema'),
    path('docs/',       SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-swagger-ui'),
    path('redoc/',      SpectacularRedocView.as_view(url_name='api-schema'),   name='api-redoc'),

    # Reports
    path('reports/portfolio/', PortfolioReportView.as_view(), name='api-portfolio-report'),

    # ViewSets
    path('', include(router.urls)),
]

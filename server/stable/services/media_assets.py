from __future__ import annotations

from stable.models import MediaAsset, MediaAssetStatus, NewsArticle, NewsImage

from .storage import current_media_provider, download_image


def localize_news_image(article: NewsArticle, image: NewsImage) -> MediaAsset:
    local_path = image.local_path
    if not local_path and image.original_url:
        local_path = download_image(image.original_url)
        image.local_path = local_path
        image.save(update_fields=["local_path", "updated_at"])

    asset, _created = MediaAsset.objects.update_or_create(
        article=article,
        source_image=image,
        defaults={
            "original_image_url": image.original_url,
            "internal_image_url": local_path,
            "storage_provider": current_media_provider(),
            "status": MediaAssetStatus.READY if local_path else MediaAssetStatus.FAILED,
        },
    )
    return asset


def set_cover_asset(article: NewsArticle, asset: MediaAsset) -> None:
    article.media_assets.update(is_cover=False)
    asset.is_cover = True
    asset.save(update_fields=["is_cover", "updated_at"])
    article.cover_media_asset = asset
    article.save(update_fields=["cover_media_asset", "updated_at"])

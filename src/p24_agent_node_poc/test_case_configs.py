"""
Test case definitions for the 6 predefined use cases.

Each TestCaseConfig defines: input files (small/large variants), output columns,
and instructions. Used by the Streamlit pages to load inputs and run the agent.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


@dataclass(frozen=True)
class InputFileSpec:
    """Single input file: display label + path relative to project root."""
    label: str
    relative_path: str


@dataclass(frozen=True)
class VariantSpec:
    """One variant (e.g. small or large): tuple of input files."""
    files: Tuple[InputFileSpec, ...]


@dataclass(frozen=True)
class TestCaseConfig:
    """Full config for one use case: schema, instructions, small/large variants."""
    key: str
    title: str
    description: str
    output_columns: List[Dict[str, str]]  # name + description per column
    additional_instructions: str
    variants: Dict[str, VariantSpec]  # "small" | "large" -> InputFileSpecs


PROJECT_ROOT = Path(__file__).resolve().parents[2]  # Project root (parent of src/)

# All 6 use cases: UC1 normalize URLs, UC2 packshot, UC3 multi-images, etc.
TEST_CASES: Dict[str, TestCaseConfig] = {
    "uc1_normalize_urls": TestCaseConfig(
        key="uc1_normalize_urls",
        title="Use Case 1 - Normalize URL Inputs",
        description=(
            "Normalize messy URL inputs where multiple links can exist in one cell or mixed text. "
            "Expected behavior: one URL per output row."
        ),
        output_columns=[
            {
                "name": "source_row_ref",
                "description": "Original row identifier from the input dataset.",
            },
            {
                "name": "normalized_url",
                "description": "Exactly one URL per row. Split rows when multiple URLs exist in one source cell.",
            },
            {
                "name": "normalization_comment",
                "description": "Short note only when a URL could not be parsed cleanly.",
            },
        ],
        additional_instructions=(
            "Treat separators like comma, semicolon, pipe, and line breaks as possible URL separators. "
            "Keep only valid HTTP/HTTPS URLs."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc1_normalize_urls/small_input.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc1_normalize_urls/large_input.csv"),
                )
            ),
        },
    ),
    "uc2_packshot_dimensions": TestCaseConfig(
        key="uc2_packshot_dimensions",
        title="Use Case 2 - Product Packshot and Dimensions",
        description=(
            "From a product URL, extract the main product image URL and the product dimensions when available."
        ),
        output_columns=[
            {"name": "Product Label", "description": "The label / name of the product."},
            {"name": "product_page_url", "description": "Input product page URL."},
            {"name": "main_packshot_url", "description": "Main product image URL (packshot)."},
            {"name": "width_cm", "description": "Product width in cm if found, otherwise blank."},
            {"name": "depth_cm", "description": "Product depth in cm if found, otherwise blank."},
            {"name": "height_cm", "description": "Product height in cm if found, otherwise blank."},
            {
                "name": "dimensions_text_raw",
                "description": "Original dimensions text snippet used as source evidence.",
            },
        ],
        additional_instructions=(
            "When dimensions are missing, keep the numeric columns empty and keep a short reason in dimensions_text_raw."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc2_packshot_dimensions/small_input.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc2_packshot_dimensions/large_input.csv"),
                )
            ),
        },
    ),
    "uc3_product_multi_images": TestCaseConfig(
        key="uc3_product_multi_images",
        title="Use Case 3 - Product Multi-Image Extraction",
        description=(
            "From a product page URL, extract all product images. One image per column and add more columns if needed."
        ),
        output_columns=[
            {"name": "product_page_url", "description": "Input product page URL."},
            {
                "name": "image_url_1",
                "description": "First product image URL. If more images exist, create image_url_2, image_url_3, etc.",
            },
            {
                "name": "total_images_found",
                "description": "Total number of images extracted for the product.",
            },
        ],
        additional_instructions=(
            "Return product images only when possible. If the page mixes lifestyle and product visuals, prioritize product visuals."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc3_product_multi_images/small_input.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc3_product_multi_images/large_input.csv"),
                )
            ),
        },
    ),
    "uc4_match_tables_chairs": TestCaseConfig(
        key="uc4_match_tables_chairs",
        title="Use Case 4 - Table and Chair Matching",
        description=(
            "Given table products and a chair catalog from the same merchant, find the best matching chair for each table."
        ),
        output_columns=[
            {"name": "table_ean", "description": "EAN identifier of the table."},
            {"name": "table_url", "description": "Table product page URL."},
            {"name": "best_chair_ean", "description": "EAN identifier of the best matching chair."},
            {"name": "best_chair_url", "description": "URL of the best matching chair."},
            {
                "name": "matching_reason",
                "description": "Short explanation of why this chair matches this table.",
            },
        ],
        additional_instructions=(
            "The first input file is the table list. The second input file is the chair catalog. "
            "Prioritize style and color compatibility from available product information."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Tables dataset", "data/test_cases/uc4_match_tables_chairs/small_tables.csv"),
                    InputFileSpec("Chairs dataset", "data/test_cases/uc4_match_tables_chairs/small_chairs.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Tables dataset", "data/test_cases/uc4_match_tables_chairs/large_tables.csv"),
                    InputFileSpec("Chairs dataset", "data/test_cases/uc4_match_tables_chairs/large_chairs.csv"),
                )
            ),
        },
    ),
    "uc5_complementary_products": TestCaseConfig(
        key="uc5_complementary_products",
        title="Use Case 5 - Complementary Products",
        description=(
            "Input is one product URL (any product type). Find products that complement it on the same merchant site."
        ),
        output_columns=[
            {
                "name": "product_url",
                "description": "Input product URL from the dataset.",
            },
            {
                "name": "recommended_product_url_1",
                "description": "Best first complementary product URL from the same site.",
            },
            {
                "name": "recommended_product_url_2",
                "description": "Second complementary product URL from the same site.",
            },
            {
                "name": "recommended_product_url_3",
                "description": "Third complementary product URL from the same site.",
            },
            {
                "name": "recommended_product_types",
                "description": "Short comma-separated list of recommended product types (e.g., rug, lamp, side table).",
            },
            {
                "name": "recommendation_reason",
                "description": "Short reason based on style, color, room usage, and product type compatibility.",
            },
        ],
        additional_instructions=(
            "Infer the input product type from the page and choose complementary categories accordingly. "
            "Do not assume all rows are the same product type."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc5_complementary_products/small_input.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc5_complementary_products/large_input.csv"),
                )
            ),
        },
    ),
    "uc6_inspiration_lifestyle_images": TestCaseConfig(
        key="uc6_inspiration_lifestyle_images",
        title="Use Case 6 - Inspiration Lifestyle Images",
        description=(
            "Collect lifestyle inspiration image URLs for a seed query and target site section."
        ),
        output_columns=[
            {"name": "search_seed", "description": "Input inspiration query text."},
            {
                "name": "lifestyle_image_url_1",
                "description": "First lifestyle image URL. Add lifestyle_image_url_2, lifestyle_image_url_3, etc. as needed.",
            },
            {
                "name": "source_page_url",
                "description": "Source page where the image was found.",
            },
            {
                "name": "collection_note",
                "description": "Short note if URL is placeholder or if extraction is limited.",
            },
        ],
        additional_instructions=(
            "Prefer real lifestyle scenes over product cutouts. This dataset includes placeholder target sections for later completion."
        ),
        variants={
            "small": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc6_inspiration_lifestyle_images/small_input.csv"),
                )
            ),
            "large": VariantSpec(
                files=(
                    InputFileSpec("Input dataset", "data/test_cases/uc6_inspiration_lifestyle_images/large_input.csv"),
                )
            ),
        },
    ),
}


def load_variant_input_files(case_key: str, variant_key: str) -> List[tuple[str, Path, pd.DataFrame]]:
    """Load CSVs for a use case variant. Returns list of (label, path, dataframe)."""
    config = TEST_CASES[case_key]
    variant = config.variants[variant_key]
    loaded: List[tuple[str, Path, pd.DataFrame]] = []
    for file_spec in variant.files:
        file_path = PROJECT_ROOT / file_spec.relative_path
        loaded.append((file_spec.label, file_path, pd.read_csv(file_path)))
    return loaded

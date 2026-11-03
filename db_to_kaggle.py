"""Export the database to anime_list.csv and reviews.csv, the layout of the Kaggle dataset.

    python db_to_kaggle.py
"""

from malcrawler import cli

if __name__ == "__main__":
    cli.run_export()

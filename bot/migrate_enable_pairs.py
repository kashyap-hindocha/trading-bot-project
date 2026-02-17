#!/usr/bin/env python3
"""
Migration script to enable all pairs by default.
This fixes Issue #4 where pairs are not enabled by default.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, '/home/ubuntu/trading-bot/bot')

import db

def migrate():
    """Enable all existing pairs that are currently disabled."""
    print("Starting migration: Enabling all pairs by default...")
    
    try:
        # Initialize database
        db.init_db()
        
        # Get all pair configs
        conn = db.get_conn()
        c = conn.cursor()
        
        # Update all pairs to enabled=1
        c.execute("UPDATE pair_config SET enabled = 1 WHERE enabled = 0 OR enabled IS NULL")
        affected = c.rowcount
        conn.commit()
        
        print(f"✓ Enabled {affected} pairs")
        
        # Verify
        c.execute("SELECT COUNT(*) FROM pair_config WHERE enabled = 1")
        enabled_count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM pair_config")
        total_count = c.fetchone()[0]
        
        print(f"✓ Total pairs: {total_count}")
        print(f"✓ Enabled pairs: {enabled_count}")
        print("✓ Migration complete!")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()

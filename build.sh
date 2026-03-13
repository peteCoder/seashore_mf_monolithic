#!/bin/bash
set -e errexit

echo "================================"
echo "Starting Django Build for Vercel"
echo "================================"

# Update pip
echo "📦 Updating pip..."
python3 -m pip install --upgrade pip

# Install dependencies
echo "📦 Installing dependencies..."
python3 -m pip install -r requirements.txt

# Collect static files
echo "📁 Collecting static files..."
python3 manage.py collectstatic --noinput --clear

# Verify static files were collected
echo "✅ Verifying static files..."
if [ -d "staticfiles" ]; then
    echo "✅ staticfiles directory exists"
    echo "Contents:"
    ls -la staticfiles/
    
    if [ -d "staticfiles/admin" ]; then
        echo "✅ Admin static files found"
        echo "Admin CSS files:"
        ls -lh staticfiles/admin/css/ 2>/dev/null || echo "CSS directory check failed"
    else
        echo "❌ WARNING: Admin static files NOT found!"
    fi
else
    echo "❌ ERROR: staticfiles directory NOT created!"
    exit 1
fi

echo "================================"
echo "✅ Build completed!"
echo "================================"
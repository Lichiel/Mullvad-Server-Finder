from setuptools import setup, find_packages

setup(
    name="mullvad-server-finder",
    version="1.0.0",
    description="A GUI application to find the fastest Mullvad VPN server",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(),
    install_requires=[
        "ttkthemes",  # Optional for better themes
    ],
    entry_points={
        "console_scripts": [
            "mullvad-finder=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: X11 Applications :: GTK",
        "Environment :: MacOS X :: Cocoa",
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Internet",
        "Topic :: Utilities",
    ],
    python_requires=">=3.6",
)

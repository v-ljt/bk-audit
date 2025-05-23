# Generated by Django 4.2.19 on 2025-04-14 12:26

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('risk', '0025_alter_risk_index_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='risk',
            name='created_at',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='创建时间'),
        ),
        migrations.AddField(
            model_name='risk',
            name='created_by',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32, null=True, verbose_name='创建者'),
        ),
        migrations.AddField(
            model_name='risk',
            name='updated_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='更新时间'),
        ),
        migrations.AddField(
            model_name='risk',
            name='updated_by',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32, null=True, verbose_name='修改者'),
        ),
    ]

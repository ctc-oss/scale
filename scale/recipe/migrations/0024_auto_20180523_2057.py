# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2018-05-23 20:57
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('recipe', '0023_auto_20180523_1247'),
    ]

    operations = [
        migrations.RenameField(
            model_name='recipenode',
            old_name='job_name',
            new_name='node_name',
        ),
        migrations.AddField(
            model_name='recipenode',
            name='sub_recipe',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contained_by', to='recipe.Recipe'),
        ),
        migrations.AlterField(
            model_name='recipenode',
            name='job',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='job.Job'),
        ),
        migrations.AlterField(
            model_name='recipenode',
            name='recipe',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='contains', to='recipe.Recipe'),
        ),
    ]

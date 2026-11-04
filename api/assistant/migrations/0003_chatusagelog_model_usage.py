from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('assistant', '0002_chatusagelog_confidence_basis_and_more')]
    operations = [
        migrations.AddField(model_name='chatusagelog', name='token_source',
            field=models.CharField(default='unavailable', max_length=24)),
        migrations.AddField(model_name='chatusagelog', name='model_name',
            field=models.CharField(blank=True, default='', max_length=128)),
    ]

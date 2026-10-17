# Set up Instagram Webhooks


Use this guide to set up Instagram Webhooks. Set up the callback before you enable notifications for an app user's account.

## Requirements {#requirements}

Your app must be **Live** to receive notifications for app users. Your Instagram API setup controls which permissions, token, host, and account ID you use.

## Limitations

- Advanced Access is required for `comments` and `live_comments` notifications.
- The account that owns the media must be public. Private accounts do not receive comment or mention notifications.
- Comment notifications for live media stop when the broadcast ends.
- You cannot select fields for each app user account. An account receives every field selected for the app.
- Notifications do not include album IDs. Use the comment ID to query the album ID.
- Notifications do not return ad IDs for media used in dynamic ads.
- `story_insights` notifications contain only the first 24 hours of metrics. This limit also applies when a story is saved as a highlight.

## Step 1: Create a callback endpoint {#create-an-endpoint}

This step must be completed before you can subscribe to any webhook fields in the App Dashboard.

Your endpoint must be able to process two types of HTTPS requests: [Verification Requests](#verification-requests) and [Event Notifications](#event-notifications). Since both requests use HTTPs, your server must have a valid TLS or SSL certificate correctly configured and installed. Self-signed certificates are not supported.

The sections below explain what will be in each type of request and how to respond to them. Alternatively, you can use our [sample app](https://developers.facebook.com/docs/graph-api/webhooks/sample-apps) which is already configured to process these requests.

### Verification requests {#verification-requests}

Anytime you configure the Webhooks product in your App Dashboard, we'll send a `GET` request to your endpoint URL.  Verification requests include the following query string parameters, appended to the end of your endpoint URL. They will look something like this:

#### Sample Verification Request

```html
GET https://www.your-clever-domain-name.com/webhooks?
  hub.mode=subscribe&
  hub.challenge=1158201444&
  hub.verify_token=meatyhamhock
```

| Parameter | Sample Value | Description |
| --- | --- | --- |
| `hub.mode` | `subscribe` | This value will always be set to `subscribe`. |
| `hub.challenge` | `1158201444` | An `int` you must pass back to us. |
| `hub.verify_token` | `meatyhamhock` | A string that we grab from the **Verify Token** field in your app's App Dashboard. You will set this string when you complete the [Webhooks configuration settings](#the-steps) steps. |

**Note:** [PHP converts periods (.) to underscores (_) in parameter names](http://www.php.net/manual/en/language.variables.external.php).

#### Validating Verification Requests {#validate-requests}

Whenever your endpoint receives a verification request, it must:

* Verify that the `hub.verify_token` value matches the string you set in the **Verify Token** field when you [configure the Webhooks product](#the-steps) in your App Dashboard (you haven't set up this token string yet).
* Respond with the `hub.challenge` value.

If you are in your App Dashboard and configuring your Webhooks product (and thus, triggering a Verification Request), the dashboard will indicate if your endpoint validated the request correctly. If you are using the Graph API's [/app/subscriptions endpoint](https://developers.facebook.com/docs/graph-api/reference/app/subscriptions) to configure the Webhooks product, the API will indicate success or failure with a response.

### Event notifications {#event-notifications}

When you configure your Webhooks product, you will subscribe to specific `fields` on an `object` type (e.g., the `photos` field on the `user` object). Whenever there's a change to one of these fields, we will send your endpoint a `POST` request with a JSON payload describing the change.

For example, if you subscribed to the `user` object's `photos` field and one of your app's Users posted a Photo, we would send you a `POST` request that would look something like this:

```html
POST / HTTPS/1.1
Host: your-clever-domain-name.com/webhooks
Content-Type: application/json
X-Hub-Signature-256: sha256={super-long-SHA256-signature}
Content-Length: 311

{
  "entry": [
    {
      "time": 1520383571,
      "changes": [
        {
          "field": "photos",
          "value":
            {
              "verb": "update",
              "object_id": "10211885744794461"
            }
        }
      ],
      "id": "10210299214172187",
      "uid": "10210299214172187"
    }
  ],
  "object": "user"
}
```

#### Payload Contents

Payloads will contain an object describing the change. When you [configure the webhooks product](#the-steps), you can indicate if payloads should only contain the names of changed fields, or if payloads should include the new values as well.

We format all payloads with JSON, so you can parse the payload using common JSON parsing methods or packages.

**Warning:** You will not be able to query historical webhook event notification data, so be sure to capture and store any webhook payload content that you want to keep.

Most payloads will contain the following common properties, but the contents and structure of each payload varies depending on the object fields you are subscribed to. Refer to each object's [reference](https://developers.facebook.com/docs/graph-api/webhooks/reference) document to see which fields will be included.

| Property | Description | Type |
| --- | --- | --- |
| `object` | The object's type (e.g., `user`, `page`, etc.) | `string` |
| `entry` | An array containing an object describing the changes. Multiple changes from different objects that are of the same type may be batched together. | `array` |
| `id` | The object's ID | `string` |
| `changed_fields` | An array of strings indicating the names of the fields that have been changed. Only included if you *disable* the **Include Values** setting when configuring the Webhooks product in your app's App Dashboard. | `array` |
| `changes` | An array containing an object describing the changed fields and their new values. Only included if you *enable* the **Include Values** setting when configuring the Webhooks product in your app's App Dashboard. | `array` |
| `time` | A UNIX timestamp indicating when the Event Notification was sent (not when the change that triggered the notification occurred). | `int` |

#### Validating Payloads {#validate-payloads}

We sign all Event Notification payloads with a **SHA256** signature and include the signature in the request's `X-Hub-Signature-256` header, preceded with `sha256=`. You don't have to validate the payload, but you should.

To validate the payload:

1. Generate a **SHA256** signature using the payload and your app's **App Secret**.
1. Compare your signature to the signature in the `X-Hub-Signature-256` header (everything after `sha256=`). If the signatures match, the payload is genuine.

#### Responding to Event Notifications

Your endpoint should respond to all Event Notifications with `200 OK HTTPS`.

#### Frequency

Event Notifications are aggregated and sent in a batch with a **maximum** of 1000 updates. However batching cannot be guaranteed so be sure to adjust your servers to handle each Webhook individually.

If any update sent to your server fails, we will retry immediately, then try a few more times with decreasing frequency over the next 36 hours. Your server should handle deduplication in these cases. Unacknowledged responses will be dropped after 36 hours.

Note: The frequency with which Messenger event notifications are sent is different. Please refer to the [Messenger Platform Webhooks documentation](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks) for more information.

## Step 2: Subscribe your app to fields {#enable-subscriptions}

In the App Dashboard, open Webhooks for your Instagram API setup. Add the callback URL and verify token. Verify the endpoint, then select the fields that your app needs.

Use the [Instagram webhook fields and permissions](https://developers.facebook.com/documentation/instagram-platform/webhooks/fields) matrix to find supported fields. Ask only for the permissions that your app needs.

### Instagram credentials

For Instagram Login, use an Instagram User access token. Send a `POST` request to the account's `/subscribed_apps` edge.

```curl
curl -i -X POST \
  "https://graph.instagram.com/v26.0/<INSTAGRAM_ACCOUNT_ID>/subscribed_apps
  ?subscribed_fields=<WEBHOOK_FIELDS>
  &access_token=<INSTAGRAM_USER_ACCESS_TOKEN>"
```

Set `<WEBHOOK_FIELDS>` to the fields selected in the App Dashboard. Separate field names with commas. A successful request returns:

```json
{
  "success": true
}
```

### Facebook credentials

For Facebook Login, use a Facebook Page access token. Send a `POST` request to the linked Page's `/subscribed_apps` edge.

```curl
curl -i -X POST \
  "https://graph.facebook.com/v26.0/<FACEBOOK_PAGE_ID>/subscribed_apps
  ?subscribed_fields=<WEBHOOK_FIELDS>
  &access_token=<FACEBOOK_PAGE_ACCESS_TOKEN>"
```

You can use `/me` when the token represents the linked Facebook Page. Set `<WEBHOOK_FIELDS>` to the fields selected in the App Dashboard. Separate field names with commas.

A successful request returns:

```json
{
  "success": true
}
```

## Step 3: Configure mutual TLS {#mtls-for-webhooks}

Mutual TLS (mTLS) is a method for mutual authentication.

mTLS ensures that the parties at each end of a network connection are who they claim to be by verifying that they both have the correct private key. The information within their respective TLS certificates provides additional verification.

### How to configure mTLS

Once you enable mTLS on your subscription to WhatsApp Business Account, Meta will present a client certificate together with its signing intermediate certificate. Both certificates are used to create a TLS handshake of Webhook requests to your server. Your server then can verify the sender’s identity of these requests by the trust chain and the common name (CN).

The client certificate is signed by a Meta-owned Certificate Authority (CA). Configure your server or load balancer to trust the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem). This certificate replaces the previous DigiCert-signed certificate, which expired on April 15, 2026.  

### Client certificate verification

After setting up HTTPS for receiving Webhook requests, complete the following steps to verify the client certificate and its common name `client.webhooks.fbclientcerts.com`:

1. Install the Meta outbound API CA certificate  
1. Verify the client certificate against the CA certificate
1. Verify the common name (client.webhooks.fbclientcerts.com) of the client certificate  

Note: Servers receiving Webhooks must be using HTTPS; and we are always verifying the certificate from your HTTPS server for security.

### Example

Depending on your server’s setup, the above steps vary in details. We illustrate by two examples, one for Nginx and one for AWS Application Load Balancer (ALB).

### Nginx

1. Download the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem) to your server, for example to `/etc/ssl/certs/meta-outbound-api-ca-2025-12.pem`

1. Turn on mTLS by Nginx directives
```
ssl_verify_client          on;
ssl_client_certificate     /etc/ssl/certs/meta-outbound-api-ca-2025-12.pem;
ssl_verify_depth           3;
```

3. Verify the CN from Nginx embedded variable `$ssl_client_s_dn` equals `"client.webhooks.fbclientcerts.com"` (
```
if ($ssl_client_s_dn ~ "CN=client.webhooks.fbclientcerts.com") {
        return 200 "$ssl_client_s_dn";
}
```

### AWS Application Load Balancer (ALB)

1. Download the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem) to an S3 bucket.
1. Configure the HTTPS listener on the ALB to enable mTLS with the trust store containing the Meta CA certificate in the S3 bucket.
1. In your application code, extract the CN from the HTTP header ["X-Amzn-Mtls-Clientcert-Subject"](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/mutual-authentication.html), and verify it equals                      `"client.webhooks.fbclientcerts.com"`.

### Downloadable CA certificate  

meta-outbound-api-ca-2025-12.pem

## Step 4: Test delivery {#test-setup}

1. Use **Test** for a selected field in the App Dashboard. Confirm that your endpoint receives the sample notification.
2. Trigger an event for the connected account. For a messaging app, send the account a test message.
3. Confirm that your endpoint checks the signature and returns a successful HTTPS response.
4. Confirm that duplicate notifications do not repeat an action.
5. Compare the payload with the [Webhook notification examples](https://developers.facebook.com/documentation/instagram-platform/webhooks/examples).

## Troubleshooting checklist

If your endpoint does not receive notifications, check that:

- The callback URL passed its check and is reachable over HTTPS.
- Your app selected the expected field.
- Notifications are enabled for the app user account.
- The token matches the login setup used by the request.
- The app has the right access level for the field.
- The account meets the field rules.
- Your server returns a success response before it starts slow work.

Do not include access tokens, app secrets, or client credentials in logs or support requests.

## Sample application {#sample-application}

The [Graph API Webhooks sample application](https://github.com/fbsamples/graph-api-webhooks-samples) shows how a server can process verification requests and notifications. Review its storage, security, and deployment settings before using it in production.

### Configure the sample application {#sample-app-on-github}

The sample is a Node.js app that uses `body-parser`, `express`, and `express-x-hub`. It can be deployed to Heroku for testing.

To configure the sample:

1. Create a Heroku account and deploy the sample app.
2. In the Meta App Dashboard, open **App settings > Basic** and copy the app secret.
3. Choose a verify-token string.
4. In the Heroku app settings, create `APP_SECRET` and `TOKEN` configuration variables. Set `APP_SECRET` to the app secret and `TOKEN` to the verify-token string.
5. Open the Heroku app URL. An empty array (`[]`) appears before notifications are received.
6. Use the Heroku app URL with `/facebook` appended as the callback URL.
7. Use the `TOKEN` value as the verify token when configuring Webhooks in the App Dashboard.

### Verify the sample application {#verifying-the-sample-app}

1. In the App Dashboard, open the Webhooks product and select **Test** for a webhook field.
2. Review the sample payload, then select **Send to My Server**.
3. Confirm that the notification appears at the Heroku app URL. You can also run `curl https://<YOUR_SUBDOMAIN>.herokuapp.com`.

## Next steps

- Learn how to [send and receive messages from Instagram professional accounts](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).
- Review [Webhooks from Meta](https://developers.facebook.com/docs/graph-api/webhooks).
